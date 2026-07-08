from __future__ import annotations

import re
from typing import Protocol

from .models import CandidateEvidence, NodeIndexEntry, ReferenceSearchSpec, TreeReferenceCandidate, TreeReferenceResolveInput
from .search_spec_builder import tokenize


class EmbeddingRetrieverProtocol(Protocol):
    def score(self, query: str, entries: list[NodeIndexEntry]) -> dict[tuple[str, str], float]: ...


_ALIASES = {
    "列表": ("list", "parent list", "parent_list"), "明细": ("detail", "list"),
    "字段": ("field", "leaf"), "费用": ("fee", "expense"), "订户": ("subscriber", "customer"),
}


class CandidateRetriever:
    def __init__(self, embedding_retriever: EmbeddingRetrieverProtocol | None = None):
        self.embedding_retriever = embedding_retriever

    def retrieve(self, request: TreeReferenceResolveInput, spec: ReferenceSearchSpec, node_index: list[NodeIndexEntry]) -> list[TreeReferenceCandidate]:
        query_text = " ".join(value for value in (request.query, request.annotation or "") if value).lower()
        keywords = list(spec.target_keywords)
        for keyword in list(keywords):
            keywords.extend(_ALIASES.get(keyword, ()))
        keywords = list(dict.fromkeys(token.lower() for token in keywords if token))
        embedding_scores = self.embedding_retriever.score(query_text, node_index) if self.embedding_retriever else {}
        candidates: list[TreeReferenceCandidate] = []
        for entry in node_index:
            evidence: list[CandidateEvidence] = []
            exact_fields = [entry.node_id, entry.json_path, entry.xml_path, entry.xml_name or ""]
            exact_hits = [
                field for field in exact_fields
                if field and re.search(rf"(?<![\w]){re.escape(field.lower())}(?![\w/])", query_text)
            ]
            if exact_hits:
                evidence.append(CandidateEvidence(source="exact", score=1.0, reason=f"query explicitly references {exact_hits[0]}"))
            normalized_search = " ".join(tokenize(entry.search_text))
            hits = [keyword for keyword in keywords if keyword in normalized_search or keyword in entry.search_text.lower()]
            if hits:
                score = min(1.0, len(set(hits)) / max(1, min(5, len(set(keywords)))))
                evidence.append(CandidateEvidence(source="lexical", score=score, reason=f"matched keywords: {', '.join(dict.fromkeys(hits))}"))
            if spec.expected_node_types and entry.tree_node_type in spec.expected_node_types:
                evidence.append(CandidateEvidence(source="structural", score=1.0, reason=f"node type is {entry.tree_node_type}"))
            embedding_score = embedding_scores.get((entry.node_id, entry.json_path), 0.0)
            if embedding_score > 0:
                evidence.append(CandidateEvidence(source="embedding", score=min(1.0, embedding_score), reason="embedding similarity"))
            if evidence:
                candidates.append(TreeReferenceCandidate(
                    node_id=entry.node_id, json_path=entry.json_path, xml_path=entry.xml_path,
                    xml_name=entry.xml_name, tree_node_type=entry.tree_node_type,
                    annotation=entry.annotation, raw_evidence=evidence,
                    evidence=[item.reason for item in evidence], match_reason="; ".join(item.reason for item in evidence),
                ))
        return candidates
