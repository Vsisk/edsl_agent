from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.context_manager.errors import ContextBuildError
from agent.context_pack.models import Authority, ContextItem, ContextPack, PackStatus, SectionStatus


CONTEXT_PACK_FAILED = "CONTEXT_PACK_FAILED"


class NamingSqlSelectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query_terms: list[str] = Field(default_factory=list)
    authoritative_facts: list[dict[str, Any]] = Field(default_factory=list)
    normative_rules: list[dict[str, Any]] = Field(default_factory=list)
    reference_examples: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NamingSqlContextAdapter:
    def __init__(self, *, max_items_per_section: int = 10, max_chars: int = 12000) -> None:
        self.max_items_per_section = max_items_per_section
        self.max_chars = max_chars

    def adapt(self, pack: ContextPack) -> NamingSqlSelectionContext:
        if pack.status == PackStatus.FAILED:
            raise ContextBuildError(CONTEXT_PACK_FAILED, "context pack has no usable content")

        groups: dict[Authority, list[dict[str, Any]]] = {
            Authority.AUTHORITATIVE: [],
            Authority.NORMATIVE: [],
            Authority.REFERENCE: [],
        }
        warnings: list[str] = []
        remaining = self.max_chars
        trimmed = False
        for section in pack.sections:
            if section.status != SectionStatus.READY:
                warnings.append(f"SECTION_{section.status.value.upper()}:{section.resource_name.value}")
            for item in section.items[: self.max_items_per_section]:
                payload = self._item_signal(item)
                size = len(item.summary)
                if size > remaining:
                    trimmed = True
                    continue
                groups[item.authority].append(payload)
                remaining -= size
            trimmed = trimmed or len(section.items) > self.max_items_per_section

        warnings.extend(f"PACK_WARNING:{warning.code}" for warning in pack.warnings)
        warnings.extend(
            f"CONFLICT:{conflict.fact_key}:{conflict.resolution}" for conflict in pack.conflicts
        )
        warnings.extend(f"TRACE:{item.source}:{item.action}" for item in pack.trace)
        if trimmed:
            warnings.append("CONTEXT_ADAPTER_TRIMMED")

        query = str(pack.request_summary.get("query") or "")
        return NamingSqlSelectionContext(
            query_terms=self._terms(query),
            authoritative_facts=groups[Authority.AUTHORITATIVE],
            normative_rules=groups[Authority.NORMATIVE],
            reference_examples=groups[Authority.REFERENCE],
            warnings=list(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _item_signal(item: ContextItem) -> dict[str, Any]:
        return {
            "item_id": item.item_id,
            "summary": item.summary,
            "facts": {fact.key: fact.value for fact in item.facts},
            "locator": {
                "source_id": item.locator.source_id,
                "kind": item.locator.kind,
                "value": item.locator.value,
            },
        }

    @staticmethod
    def _terms(value: str) -> list[str]:
        return list(dict.fromkeys(re.findall(r"[\w]+", value.lower(), flags=re.UNICODE)))
