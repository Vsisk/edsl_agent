import json
from collections import defaultdict
from typing import Any

from agent.context_pack.models import (Authority, BudgetUsage, ContextConflict, ContextItem,
                                       ContextPack, ContextPackRequest, ContextSection,
                                       ContextTraceItem, PackStatus, ResourceName, SectionStatus)
from agent.context_pack.registry import CANONICAL_RESOURCE_ORDER


AUTHORITY_ORDER = {
    Authority.AUTHORITATIVE: 0,
    Authority.NORMATIVE: 1,
    Authority.REFERENCE: 2,
}


class ContextPackBuilder:
    def __init__(
        self,
        max_items_by_resource: dict[str | ResourceName, int] | None = None,
        global_max_chars: int = 50000,
    ) -> None:
        self.max_items_by_resource = {
            ResourceName(key): value for key, value in (max_items_by_resource or {}).items()
        }
        self.global_max_chars = global_max_chars

    def build(self, request: ContextPackRequest, sections: list[ContextSection]) -> ContextPack:
        section_by_name = {section.resource_name: section for section in sections}
        ordered = [section_by_name[name] for name in CANONICAL_RESOURCE_ORDER if name in section_by_name]
        trace = []
        bounded = [self._bound_section(section, trace) for section in ordered]
        bounded = self._apply_global_budget(bounded, trace)
        conflicts = self._conflicts([item for section in bounded for item in section.items])
        has_items = any(section.items for section in bounded)
        all_ready = all(section.status == SectionStatus.READY for section in bounded)
        status = PackStatus.COMPLETE if has_items and all_ready else PackStatus.PARTIAL if has_items else PackStatus.FAILED
        return ContextPack(
            status=status,
            request_summary={
                "query": request.query,
                "resource_names": [name.value for name in request.resource_names],
            },
            current_node=request.node,
            sections=bounded,
            conflicts=conflicts,
            warnings=[warning for section in bounded for warning in section.warnings],
            trace=trace,
        )

    def _bound_section(self, section: ContextSection, trace: list[ContextTraceItem]) -> ContextSection:
        seen = set()
        items = []
        for item in section.items:
            if item.resource_name != section.resource_name:
                raise ValueError(f"resource mismatch: {item.item_id}")
            key = (item.resource_name, item.item_id, item.content_hash)
            if key not in seen:
                seen.add(key)
                items.append(item)
        items.sort(key=lambda item: (
            0 if any(evidence.match_kind == "exact" for evidence in item.evidence) else 1,
            AUTHORITY_ORDER[item.authority], item.rank, item.item_id,
        ))
        limit = self.max_items_by_resource.get(section.resource_name, len(items))
        kept, trimmed = items[:limit], items[limit:]
        for item in trimmed:
            trace.append(ContextTraceItem(
                source=section.resource_name.value, action="trimmed", detail="provider item limit", item_id=item.item_id
            ))
        return section.model_copy(update={
            "items": kept,
            "budget_usage": BudgetUsage(
                item_count=len(kept),
                character_count=sum(self._item_chars(item) for item in kept),
                trimmed_count=len(trimmed),
            ),
        }, deep=True)

    def _apply_global_budget(self, sections, trace):
        remaining = self.global_max_chars
        result = []
        for section in sections:
            kept, trimmed = [], []
            for item in section.items:
                size = self._item_chars(item)
                if size <= remaining:
                    kept.append(item)
                    remaining -= size
                else:
                    trimmed.append(item)
                    trace.append(ContextTraceItem(
                        source=section.resource_name.value, action="trimmed",
                        detail="global character limit", item_id=item.item_id,
                    ))
            usage = section.budget_usage.model_copy(update={
                "item_count": len(kept),
                "character_count": sum(self._item_chars(item) for item in kept),
                "trimmed_count": section.budget_usage.trimmed_count + len(trimmed),
            })
            result.append(section.model_copy(update={"items": kept, "budget_usage": usage}, deep=True))
        return result

    @staticmethod
    def _item_chars(item: ContextItem) -> int:
        return len(json.dumps(item.content, ensure_ascii=False, sort_keys=True, default=str))

    @staticmethod
    def _conflicts(items: list[ContextItem]) -> list[ContextConflict]:
        grouped: dict[str, list[tuple[ContextItem, Any]]] = defaultdict(list)
        for item in items:
            for fact in item.facts:
                grouped[fact.key].append((item, fact.value))
        result = []
        for key, values in grouped.items():
            distinct = {}
            for item, value in values:
                distinct.setdefault(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), (item, value))
            if len(distinct) <= 1:
                continue
            authoritative = {serialized for serialized, (item, _) in distinct.items() if item.authority == Authority.AUTHORITATIVE}
            resolution = "authoritative_wins" if len(authoritative) == 1 else "unresolved"
            result.append(ContextConflict(
                fact_key=key,
                item_ids=list(dict.fromkeys(item.item_id for item, _ in values)),
                resolution=resolution,
                values=[value for _, value in distinct.values()],
            ))
        return result
