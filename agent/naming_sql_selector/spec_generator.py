import json
import re
from typing import Any

from .knowledge import (
    DevelopmentKnowledge,
    DevelopmentKnowledgeRetriever,
    NoOpDevelopmentKnowledgeRetriever,
)
from .models import AvailableValue, DataAccessSpec, NamingSqlSelectionRequest

# Defensive limits for session/request data that can flow into later reviewer prompts.
MAX_COMBINED_QUERY_CHARS = 4000
MAX_TERM_CHARS = 128
MAX_MERGED_TERMS = 50
MAX_AVAILABLE_CONTEXT = 100


def _normalize_string(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:MAX_TERM_CHARS].strip()


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = [_normalize_string(item) for item in value if isinstance(item, str)]
    return [item for item in normalized if item]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _bounded_unique(values: list[str]) -> list[str]:
    return _unique(values)[:MAX_MERGED_TERMS]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:MAX_COMBINED_QUERY_CHARS]
    except (TypeError, ValueError, RecursionError):
        return ""


def _bounded_combined_text(parts: tuple[str, ...]) -> str:
    present = [re.sub(r"\s+", " ", part).strip() for part in parts if part and part.strip()]
    if not present:
        return ""
    separator_chars = len(present) - 1
    per_part = max((MAX_COMBINED_QUERY_CHARS - separator_chars) // len(present), 1)
    return " ".join(part[:per_part] for part in present)[:MAX_COMBINED_QUERY_CHARS]


def requires_naming_sql(structured_spec: dict[str, Any], *text_values: Any) -> bool:
    """Apply the shared, deliberately narrow expression/data-access route rule."""
    explicit = structured_spec.get("requires_naming_sql")
    if isinstance(explicit, bool):
        return explicit
    inference_text = " ".join(_inference_values(value) for value in text_values)
    return any(
        re.search(pattern, inference_text, flags=re.IGNORECASE)
        for pattern in (
            r"(?<![a-z0-9])查表(?![a-z0-9])",
            r"(?<![a-z0-9])查询表(?![a-z0-9])",
            r"(?<![a-z0-9])data[\s_-]*source(?![a-z0-9])",
            r"(?<![a-z0-9])naming[\s_-]*sql(?![a-z0-9])",
        )
    )


def _inference_values(value: Any, *, _depth: int = 0, _seen: set[int] | None = None) -> str:
    """Bounded visible values only; schema keys such as data_source are not user intent."""
    if isinstance(value, str):
        return value[:MAX_COMBINED_QUERY_CHARS]
    if value is None or _depth >= 8:
        return ""
    seen = _seen if _seen is not None else set()
    if isinstance(value, (dict, list, tuple)):
        if id(value) in seen:
            return ""
        seen.add(id(value))
        items = value.values() if isinstance(value, dict) else value
        result = " ".join(_inference_values(item, _depth=_depth + 1, _seen=seen) for item in items)
        seen.remove(id(value))
        return result[:MAX_COMBINED_QUERY_CHARS]
    return str(value)[:MAX_TERM_CHARS]


def _semantic_tokens(*values: str) -> list[str]:
    tokens: list[str] = []
    for value in values:
        tokens.extend(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()))
    return _unique(tokens)


class DataAccessSpecGenerator:
    def __init__(self, retriever: DevelopmentKnowledgeRetriever | None = None):
        self._retriever = retriever or NoOpDevelopmentKnowledgeRetriever()

    def retrieve_knowledge(self, request: NamingSqlSelectionRequest) -> list[DevelopmentKnowledge]:
        structured = request.structured_spec
        business_terms = _strings(structured.get("business_terms", []))
        scope_terms = _strings(structured.get("scope_terms", []))
        bo_hints = _strings(structured.get("bo_hints", []))
        filter_requirements = _strings(structured.get("filter_requirements", []))
        combined = _bounded_combined_text((
            request.query, _safe_text(request.node), _safe_text(request.parent_node),
            _safe_text(structured), " ".join(business_terms + scope_terms + bo_hints + filter_requirements),
        ))
        try:
            returned = self._retriever.retrieve(request.site_id, combined, limit=5)
        except Exception:
            returned = []
        return self.validate_knowledge(returned)

    @staticmethod
    def validate_knowledge(returned: Any) -> list[DevelopmentKnowledge]:
        bounded: list[DevelopmentKnowledge] = []
        for item in returned if isinstance(returned, list) else []:
            try:
                entry = item if isinstance(item, DevelopmentKnowledge) else DevelopmentKnowledge.model_validate(item)
            except Exception:
                continue
            bounded.append(entry)
            if len(bounded) == 5:
                break
        return bounded

    def generate(self, request: NamingSqlSelectionRequest, knowledge: list[DevelopmentKnowledge] | None = None) -> DataAccessSpec:
        structured = request.structured_spec
        business_terms = _strings(structured.get("business_terms", []))
        scope_terms = _strings(structured.get("scope_terms", []))
        bo_hints = _strings(structured.get("bo_hints", []))
        filter_requirements = _strings(structured.get("filter_requirements", []))
        requires_naming_sql_value = requires_naming_sql(structured, request.query, request.node, request.parent_node)

        available_values: list[AvailableValue] = []
        for item in request.available_context[:MAX_AVAILABLE_CONTEXT]:
            if not isinstance(item, dict):
                continue
            name, source_ref = item.get("name"), item.get("source_ref")
            if not isinstance(name, str) or not isinstance(source_ref, str):
                continue
            explicit_tags = _strings(item.get("semantic_tags", []))
            normalized_name = _normalize_string(name)
            normalized_source_ref = _normalize_string(source_ref)
            if not normalized_name or not normalized_source_ref:
                continue
            data_type = item.get("data_type", "")
            available_values.append(AvailableValue(
                name=normalized_name,
                source_ref=normalized_source_ref,
                data_type=_normalize_string(data_type) if isinstance(data_type, str) else "",
                semantic_tags=_bounded_unique(explicit_tags + _semantic_tokens(normalized_name, normalized_source_ref)),
                is_list=item.get("is_list", False) if isinstance(item.get("is_list", False), bool) else False,
            ))

        bounded_knowledge = self.retrieve_knowledge(request) if knowledge is None else self.validate_knowledge(knowledge)
        for entry in bounded_knowledge:
            bo_hints.extend(_strings(entry.bo_names))
            business_terms.extend(_strings(entry.semantic_tags))

        return DataAccessSpec(
            requires_naming_sql=requires_naming_sql_value,
            business_terms=_bounded_unique(business_terms),
            scope_terms=_bounded_unique(scope_terms),
            bo_hints=_bounded_unique(bo_hints),
            filter_requirements=_bounded_unique(filter_requirements),
            available_values=available_values,
            allow_full_table=structured.get("allow_full_table", False)
            if isinstance(structured.get("allow_full_table", False), bool) else False,
        )
