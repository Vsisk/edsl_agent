from __future__ import annotations

import json
from copy import deepcopy

from .models import ContextPack


class ContextPackPromptRenderer:
    def __init__(self, *, max_items: int = 30, max_chars: int = 20000) -> None:
        self.max_items = max_items
        self.max_chars = max_chars

    def render_json(self, pack: ContextPack) -> str:
        value = {
            "status": pack.status.value,
            "sections": [
                {"resource_name": section.resource_name.value,
                 "status": section.status.value, "items": []}
                for section in pack.sections
            ],
            "warnings": [item.code for item in pack.warnings],
            "conflicts": [
                {"fact_key": item.fact_key, "resolution": item.resolution}
                for item in pack.conflicts
            ],
            "trace": [
                {"source": item.source, "action": item.action, "item_id": item.item_id}
                for item in pack.trace
            ],
        }
        count = 0
        for output_section, section in zip(value["sections"], pack.sections):
            for item in section.items:
                if count >= self.max_items:
                    break
                projection = {
                    "item_id": item.item_id,
                    "authority": item.authority.value,
                    "item_type": item.item_type,
                    "summary": item.summary[:512],
                    "facts": {fact.key: fact.value for fact in item.facts},
                }
                node = self._project_node(section, item)
                if node is not None:
                    projection["node"] = node
                output_section["items"].append(projection)
                rendered = self._dump(value)
                if len(rendered) > self.max_chars:
                    output_section["items"].pop()
                    if "CONTEXT_PACK_PROMPT_TRIMMED" not in value["warnings"]:
                        value["warnings"].append("CONTEXT_PACK_PROMPT_TRIMMED")
                    return self._bounded_dump(value)
                count += 1
        return self._bounded_dump(value)

    @staticmethod
    def _project_node(section, item) -> dict | None:
        if section.resource_name.value != "current_tree" or item.item_type not in {"node", "field"}:
            return None
        value = item.content.get("value")
        if not isinstance(value, dict):
            return None
        return {key: deepcopy(field_value) for key, field_value in value.items() if key != "children"}

    def _bounded_dump(self, value) -> str:
        rendered = self._dump(value)
        if len(rendered) <= self.max_chars:
            return rendered
        minimal = {"status": value["status"], "sections": [], "warnings": ["CONTEXT_PACK_PROMPT_TRIMMED"],
                   "conflicts": [], "trace": []}
        rendered = self._dump(minimal)
        return rendered[: self.max_chars]

    @staticmethod
    def _dump(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
