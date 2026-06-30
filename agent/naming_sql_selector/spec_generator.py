import json
import re
from typing import Any

from .knowledge import (
    DevelopmentKnowledge,
    DevelopmentKnowledgeRetriever,
    NoOpDevelopmentKnowledgeRetriever,
)
from .models import AvailableValue, DataAccessSpec, NamingSqlSelectionRequest


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _semantic_tokens(*values: str) -> list[str]:
    tokens: list[str] = []
    for value in values:
        tokens.extend(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()))
    return _unique(tokens)


class DataAccessSpecGenerator:
    def __init__(self, retriever: DevelopmentKnowledgeRetriever | None = None):
        self._retriever = retriever or NoOpDevelopmentKnowledgeRetriever()

    def generate(self, request: NamingSqlSelectionRequest) -> DataAccessSpec:
        structured = request.structured_spec
        combined = " ".join(
            part for part in (
                request.query,
                json.dumps(request.node, ensure_ascii=False, default=str),
                json.dumps(request.parent_node, ensure_ascii=False, default=str),
            ) if part
        )
        if isinstance(structured.get("requires_naming_sql"), bool):
            requires_naming_sql = structured["requires_naming_sql"]
        else:
            requires_naming_sql = any(
                re.search(pattern, combined, flags=re.IGNORECASE)
                for pattern in (
                    r"(?<![a-z0-9])查表(?![a-z0-9])",
                    r"(?<![a-z0-9])查询表(?![a-z0-9])",
                    r"(?<![a-z0-9])data[\s_-]*source(?![a-z0-9])",
                    r"(?<![a-z0-9])naming[\s_-]*sql(?![a-z0-9])",
                )
            )

        available_values: list[AvailableValue] = []
        for item in request.available_context:
            if not isinstance(item, dict):
                continue
            name, source_ref = item.get("name"), item.get("source_ref")
            if not isinstance(name, str) or not isinstance(source_ref, str):
                continue
            explicit_tags = _strings(item.get("semantic_tags", []))
            available_values.append(AvailableValue(
                name=name,
                source_ref=source_ref,
                data_type=item.get("data_type", "") if isinstance(item.get("data_type", ""), str) else "",
                semantic_tags=_unique(explicit_tags + _semantic_tokens(name, source_ref)),
            ))

        business_terms = _strings(structured.get("business_terms", []))
        bo_hints = _strings(structured.get("bo_hints", []))
        try:
            returned_knowledge = self._retriever.retrieve(request.site_id, combined, limit=5)
        except Exception:
            returned_knowledge = []
        knowledge: list[DevelopmentKnowledge] = []
        for item in returned_knowledge if isinstance(returned_knowledge, list) else []:
            try:
                entry = item if isinstance(item, DevelopmentKnowledge) else DevelopmentKnowledge.model_validate(item)
            except Exception:
                continue
            knowledge.append(entry)
            if len(knowledge) == 5:
                break
        for entry in knowledge:
            bo_hints.extend(_strings(entry.bo_names))
            business_terms.extend(_strings(entry.semantic_tags))

        return DataAccessSpec(
            requires_naming_sql=requires_naming_sql,
            business_terms=_unique(business_terms),
            scope_terms=_unique(_strings(structured.get("scope_terms", []))),
            bo_hints=_unique(bo_hints),
            filter_requirements=_unique(_strings(structured.get("filter_requirements", []))),
            available_values=available_values,
            allow_full_table=structured.get("allow_full_table", False)
            if isinstance(structured.get("allow_full_table", False), bool) else False,
        )
