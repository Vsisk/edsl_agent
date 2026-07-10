from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from agent.context_pack.errors import SOURCE_UNAVAILABLE, STALE_SOURCE, ContextProviderError
from agent.context_pack.models import (RetrievalEvidence, SearchDocument, SearchFilters,
                                       SearchHit, SearchResult, SourceLocator)

from .rank_fusion import reciprocal_rank_fusion


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[0-9a-zA-Z_]+|[\u4e00-\u9fff]", _normalize(value)))


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    denominator = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


class LocalResourceSearchTool:
    def __init__(self, embedding_client: Any = None) -> None:
        self.embedding_client = embedding_client
        self._documents: dict[str, tuple[SearchDocument, ...]] = {}
        self._roots: dict[str, Path] = {}

    def register_source(
        self,
        source_id: str,
        documents: list[SearchDocument] | tuple[SearchDocument, ...],
        root: str | Path | None = None,
    ) -> None:
        self._documents[source_id] = tuple(documents)
        if root is not None:
            self._roots[source_id] = Path(root).resolve()

    def search(
        self,
        source_id: str,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 5,
    ) -> SearchResult:
        if source_id not in self._documents:
            raise ContextProviderError(SOURCE_UNAVAILABLE, source_id)
        filters = filters or SearchFilters()
        documents = [doc for doc in self._documents[source_id] if not filters.item_types or doc.item_type in filters.item_types]
        normalized_query, query_tokens = _normalize(query), _tokens(query)
        exact, lexical = [], []
        for doc in documents:
            exact_fields = (_normalize(doc.item_id), _normalize(doc.summary), _normalize(doc.locator.value))
            if any(normalized_query == field or normalized_query in field for field in exact_fields if field):
                exact.append(doc.item_id)
            overlap = len(query_tokens & _tokens(f"{doc.search_text} {doc.summary}"))
            if overlap:
                lexical.append((doc.item_id, overlap))
        lexical_ids = [item_id for item_id, _ in sorted(lexical, key=lambda item: (-item[1], self._position(documents, item[0])))]
        semantic_ids: list[str] = []
        degraded, warnings = False, []
        if self.embedding_client is not None and documents:
            try:
                vectors = self.embedding_client.embed_texts([query, *[doc.search_text for doc in documents]])
                if len(vectors) == len(documents) + 1:
                    scored = [(doc.item_id, _cosine(vectors[0], vector)) for doc, vector in zip(documents, vectors[1:])]
                    semantic_ids = [item_id for item_id, score in sorted(scored, key=lambda item: (-item[1], self._position(documents, item[0]))) if score > 0]
            except Exception:
                degraded, warnings = True, ["embedding unavailable"]
        fused = reciprocal_rank_fusion([lexical_ids, semantic_ids], [doc.item_id for doc in documents])
        ordered_ids = list(dict.fromkeys([*exact, *fused]))[:max(0, limit)]
        by_id = {doc.item_id: doc for doc in documents}
        hits = []
        for rank, item_id in enumerate(ordered_ids, start=1):
            evidence = [RetrievalEvidence(source=source_id, action="recall", reason="exact identifier or name", match_kind="exact")] if item_id in exact else [RetrievalEvidence(source=source_id, action="recall", reason="lexical or semantic match", match_kind="fused")]
            hits.append(SearchHit(document=by_id[item_id], rank=rank, evidence=evidence))
        return SearchResult(hits=hits, degraded=degraded, warnings=warnings)

    @staticmethod
    def _position(documents: list[SearchDocument], item_id: str) -> int:
        return next(index for index, doc in enumerate(documents) if doc.item_id == item_id)

    def read_slice(self, locator: SourceLocator, expected_hash: str) -> str:
        root = self._roots.get(locator.source_id)
        if root is None or not locator.path:
            raise ContextProviderError(SOURCE_UNAVAILABLE, locator.source_id)
        path = (root / locator.path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ContextProviderError(SOURCE_UNAVAILABLE, "locator outside registered root") from exc
        if not path.is_file():
            raise ContextProviderError(SOURCE_UNAVAILABLE, locator.path)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        start = (locator.start_line or 1) - 1
        end = locator.end_line or len(lines)
        content = "".join(lines[start:end])
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != expected_hash:
            raise ContextProviderError(STALE_SOURCE, locator.value)
        return content
