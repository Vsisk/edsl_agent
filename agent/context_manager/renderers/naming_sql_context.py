from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class NamingSqlContextRenderer:
    """Render a deterministic, bounded and non-executable organizer view."""

    max_text_chars = 1_000
    # The assembler applies this cap before assigning aliases. Every alias it
    # passes here is therefore rendered; there is no second, hidden truncation.
    max_items = 200
    max_total_chars = 24_000
    _body_keys = {"sql", "sql_body", "sql_command", "sql_text", "query_sql", "statement"}

    def render(self, *, request: Any, global_context: Any, node_context: Any,
               logic_area_context: Any, resource_candidates: Any,
               ootb_reference_cases: Any, site_knowledge_cases: Any,
               candidate_aliases: dict[str, Any], reference_aliases: dict[str, Any]) -> str:
        candidate_rows = []
        for alias, item in candidate_aliases.items():
            candidate_rows.append({"alias": alias, "bo_name": item.bo_name,
                "naming_sql_name": item.naming_sql_name, "annotation": item.annotation,
                "param_list": item.param_list, "return_type": item.return_type,
                "evidence": item.evidence, "matched_terms": item.matched_terms})
        reference_rows = []
        for alias, item in reference_aliases.items():
            reference_rows.append({"alias": alias, "asset_type": item.asset.asset_type,
                "summary": item.asset.index_text, "evidence": item.evidence})
        payload = {
            "request": request,
            "rules": global_context,
            "node": node_context,
            "logic": logic_area_context,
            "resource": candidate_rows,
            "ootb": [row for row in reference_rows if row["asset_type"] == "ootb_case"],
            "site": [row for row in reference_rows if row["asset_type"] == "site_knowledge"],
        }
        clean = self._clean(payload)
        text = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        if len(text) > self.max_total_chars:
            # Keep the JSON valid and all selectable aliases visible even under adversarial input.
            fallback = {
                "bounded": True,
                "request": {"query": str(getattr(request, "query", ""))[:self.max_text_chars],
                            "top_k": getattr(request, "top_k", 5)},
                "resource": [{"alias": alias} for alias in candidate_aliases],
                "references": [{"alias": alias} for alias in reference_aliases],
            }
            text = json.dumps(fallback, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return text

    def _clean(self, value: Any, depth: int = 0) -> Any:
        if depth > 20:
            return None
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if isinstance(value, dict):
            return {str(key): self._clean(item, depth + 1) for key, item in sorted(value.items(), key=lambda x: str(x[0]))
                    if str(key).lower() not in self._body_keys}
        if isinstance(value, (list, tuple)):
            return [self._clean(item, depth + 1) for item in value[:self.max_items]]
        if isinstance(value, str):
            return value[:self.max_text_chars]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:self.max_text_chars]
