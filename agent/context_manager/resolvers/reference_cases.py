from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from agent.context_manager.errors import ContextBuildError, INVALID_LLM_OUTPUT
from agent.context_manager.models import (
    BuildContextRequest,
    ContextAsset,
    ContextEvidenceItem,
    NamingSqlCandidate,
    ReferenceCaseBlock,
    ReferenceCaseCandidate,
)


ReferenceAssetType = Literal["ootb_case", "site_knowledge", "history_case"]
_DEFAULT_DATA = Path(__file__).resolve().parent.parent / "mock_data"
_MAX_LINE_BYTES = 64 * 1024
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_RECORDS = 10_000


class ReferenceCaseResolver:
    """Load, recall, and rerank one bounded JSONL reference-case corpus."""

    def __init__(
        self,
        path: str | Path,
        asset_type: ReferenceAssetType,
        retriever: Any = None,
        reranker: Any = None,
        *,
        filter_site: bool = False,
    ) -> None:
        self.path = Path(path)
        self.asset_type = asset_type
        self.retriever = retriever
        self.reranker = reranker
        self.filter_site = filter_site

    def resolve(self, request: BuildContextRequest, context: Any = None) -> ReferenceCaseBlock:
        records, evidence = _load_jsonl(self.path)
        if records is None:
            return ReferenceCaseBlock(evidence_trace=evidence)

        if self.filter_site:
            records = [record for record in records if _site_matches(record, request)]

        assets: list[ContextAsset] = []
        seen_ids: set[str] = set()
        for record in records:
            asset = _to_asset(record, self.asset_type, self.path, request)
            if asset.asset_id in seen_ids:
                evidence.append(_evidence(self.path, "record_skipped", "Duplicate case ID", asset.asset_id))
                continue
            seen_ids.add(asset.asset_id)
            assets.append(asset)

        query = _query_text(request)
        recalled = assets
        if self.retriever is not None:
            recalled = self.retriever.retrieve(query, list(assets), semantic_limit=max(request.top_k, 10))
            recalled = _canonical_assets(recalled, assets, self.asset_type, "retriever")

        selected = recalled
        rerank_evidence: list[ContextEvidenceItem] = []
        if self.reranker is not None:
            result = self.reranker.rerank(query, list(recalled), context or {})
            selected = _canonical_assets(
                getattr(result, "selected_assets", None), recalled, self.asset_type, "reranker"
            )
            rerank_evidence = list(getattr(result, "evidence_trace", []) or [])

        candidates = [
            _to_candidate(asset, rank, self.asset_type)
            for rank, asset in enumerate(selected, start=1)
        ]
        for asset in selected:
            evidence.append(_evidence(self.path, "case_selected", "Selected reference case", asset.asset_id))
        return ReferenceCaseBlock(candidates=candidates, evidence_trace=[*evidence, *rerank_evidence])


class OOTBContextResolver(ReferenceCaseResolver):
    def __init__(self, path: str | Path | None = None, retriever: Any = None, reranker: Any = None) -> None:
        super().__init__(path or _DEFAULT_DATA / "ootb_cases.jsonl", "ootb_case", retriever, reranker)


class SiteKnowledgeContextResolver(ReferenceCaseResolver):
    def __init__(self, path: str | Path | None = None, retriever: Any = None, reranker: Any = None) -> None:
        super().__init__(path or _DEFAULT_DATA / "site_knowledge_cases.jsonl", "site_knowledge", retriever, reranker, filter_site=True)


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]] | None, list[ContextEvidenceItem]]:
    evidence: list[ContextEvidenceItem] = []
    if not path.is_file():
        return None, [_evidence(path, "source_missing", "Reference-case source is missing")]

    records: list[dict[str, Any]] = []
    consumed = 0
    with path.open("rb") as stream:
        for line_number in range(1, _MAX_RECORDS + 1):
            remaining = _MAX_SOURCE_BYTES - consumed
            if remaining <= 0:
                evidence.append(_evidence(path, "source_truncated", "Reference-case source byte limit reached"))
                break
            raw = stream.readline(min(_MAX_LINE_BYTES + 1, remaining + 1))
            if not raw:
                break
            consumed += len(raw)
            if len(raw) > _MAX_LINE_BYTES:
                while not raw.endswith(b"\n") and consumed < _MAX_SOURCE_BYTES:
                    chunk = stream.readline(min(_MAX_LINE_BYTES + 1, _MAX_SOURCE_BYTES - consumed))
                    if not chunk:
                        break
                    consumed += len(chunk)
                    raw = chunk
                evidence.append(_evidence(path, "record_skipped", "Oversized JSONL line", payload={"line": line_number}))
                if consumed >= _MAX_SOURCE_BYTES and not raw.endswith(b"\n"):
                    evidence.append(_evidence(path, "source_truncated", "Reference-case source byte limit reached"))
                    break
                continue
            if consumed >= _MAX_SOURCE_BYTES and not raw.endswith(b"\n"):
                evidence.append(_evidence(path, "source_truncated", "Reference-case source byte limit reached"))
                break
            if not raw.strip():
                continue
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                evidence.append(_evidence(path, "record_skipped", "Malformed UTF-8 JSONL record", payload={"line": line_number}))
                continue
            if not isinstance(value, dict):
                evidence.append(_evidence(path, "record_skipped", "JSONL record is not an object", payload={"line": line_number}))
                continue
            records.append(value)
        else:
            if stream.read(1):
                evidence.append(_evidence(path, "source_truncated", "Reference-case record limit reached"))
    return records, evidence


def _site_matches(record: dict[str, Any], request: BuildContextRequest) -> bool:
    site_id = record.get("site_id")
    project_id = record.get("project_id")
    return site_id == request.site_id and (project_id in (None, "") or project_id == request.project_id)


def _to_asset(record: dict[str, Any], asset_type: ReferenceAssetType, path: Path, request: BuildContextRequest) -> ContextAsset:
    case_id = str(record.get("case_id") or record.get("id") or "").strip()
    if not case_id:
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        case_id = hashlib.sha256(encoded).hexdigest()[:20]
    site_id = record.get("site_id")
    project_id = record.get("project_id")
    scope = "site" if asset_type in {"site_knowledge", "history_case"} else "global"
    return ContextAsset(
        asset_id=f"{asset_type}:{case_id}",
        asset_type=asset_type,
        scope=scope,
        site_id=str(site_id) if site_id not in (None, "") else (request.site_id if scope == "site" else None),
        project_id=str(project_id) if project_id not in (None, "") else None,
        logic_area_id=_first_string(record, "logic_area_id"),
        content=record,
        index_text=_semantic_text(record),
        source=str(record.get("source") or path),
        version=_first_string(record, "version"),
    )


def _semantic_text(record: dict[str, Any]) -> str:
    keys = (
        "description", "node_pattern", "node_patterns", "logic_area", "logic_area_id",
        "logic_area_terms", "query", "query_terms", "selected_bo", "bo_name", "selected_sql",
        "naming_sql", "naming_sql_id", "param_hints", "parameter_hints", "param_bindings", "bindings",
    )
    parts: list[str] = []
    for key in keys:
        if key in record:
            for text in _texts(record[key]):
                if text and text not in parts:
                    parts.append(text)
    return "; ".join(parts)[:16_000]


def _texts(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (str, int, float)):
        return [str(value).strip()]
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _texts(item)]
    return []


def _query_text(request: BuildContextRequest) -> str:
    parts = [request.query, request.target_bo_name, request.parent_bo_hint, *request.target_logic_area_id_list]
    return "\n".join(str(part).strip() for part in parts if part)[:2_000]


def _canonical_assets(returned: Any, candidates: list[ContextAsset], asset_type: ReferenceAssetType, source: str) -> list[ContextAsset]:
    if not isinstance(returned, (list, tuple)):
        raise ContextBuildError(INVALID_LLM_OUTPUT, f"{source} returned malformed asset selection")
    canonical = {asset.asset_id: asset for asset in candidates}
    selected: list[ContextAsset] = []
    seen: set[str] = set()
    for item in returned:
        if not isinstance(item, ContextAsset) or item.asset_type != asset_type:
            raise ContextBuildError(INVALID_LLM_OUTPUT, f"{source} returned malformed reference-case asset")
        if item.asset_id not in canonical:
            raise ContextBuildError(INVALID_LLM_OUTPUT, f"{source} returned unknown reference-case asset")
        if item.asset_id in seen:
            raise ContextBuildError(INVALID_LLM_OUTPUT, f"{source} returned duplicate reference-case asset")
        seen.add(item.asset_id)
        selected.append(canonical[item.asset_id])
    return selected


def _to_candidate(asset: ContextAsset, rank: int, asset_type: ReferenceAssetType) -> ReferenceCaseCandidate:
    record = asset.content
    bo = record.get("selected_bo", record.get("bo_name"))
    sql = record.get("selected_sql", record.get("naming_sql"))
    bo_name = _named(bo, "bo_name", "name", "id")
    sql_id = _named(sql, "naming_sql_id", "sql_id", "id", "sql_name", "name") or _first_string(record, "naming_sql_id")
    normalized = None
    if bo_name and sql_id:
        sql_name = _named(sql, "naming_sql_name", "sql_name", "name")
        params = sql.get("param_list") if isinstance(sql, dict) else None
        if not isinstance(params, list):
            params = record.get("param_list") if isinstance(record.get("param_list"), list) else []
        source = {"ootb_case": "ootb_reference", "site_knowledge": "site_knowledge", "history_case": "history_case"}[asset_type]
        normalized = NamingSqlCandidate(
            candidate_id=asset.asset_id,
            bo_name=bo_name,
            naming_sql_id=sql_id,
            naming_sql_name=sql_name,
            annotation=str(record.get("description") or ""),
            param_list=params,
            source=source,
            rank=rank,
            evidence=[str(item) for item in _as_list(record.get("evidence"))],
            matched_terms=_texts(record.get("query_terms")),
            retrieval_metadata={key: record[key] for key in ("param_hints", "parameter_hints", "param_bindings", "bindings", "source") if key in record},
        )
    return ReferenceCaseCandidate(asset=asset, candidate=normalized, evidence=_record_evidence(asset))


def _record_evidence(asset: ContextAsset) -> list[ContextEvidenceItem]:
    return [
        ContextEvidenceItem(source=asset.source or "reference_case", action="source_evidence", asset_id=asset.asset_id, evidence=str(item))
        for item in _as_list(asset.content.get("evidence"))
    ]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value is None else [value])


def _first_string(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return None


def _named(value: Any, *keys: str) -> str | None:
    if isinstance(value, (str, int, float)):
        return str(value).strip() or None
    if isinstance(value, dict):
        return _first_string(value, *keys)
    return None


def _evidence(path: Path, action: str, message: str, asset_id: str | None = None, payload: dict[str, Any] | None = None) -> ContextEvidenceItem:
    return ContextEvidenceItem(source=str(path), action=action, asset_id=asset_id, evidence=message, payload=payload or {})
