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

    def budget_inputs(self, candidates: list[Any], references: list[Any], requested: int) -> tuple[list[Any], list[Any]]:
        """Choose a prefix whose essential rows always fit; candidates have priority."""
        chosen_candidates: list[Any] = []
        chosen_references: list[Any] = []
        for item in candidates[:min(requested, self.max_items)]:
            trial = chosen_candidates + [item]
            if len(self._essential_json(trial, chosen_references)) > self.max_total_chars:
                break
            chosen_candidates = trial
        remaining = min(requested, self.max_items) - len(chosen_candidates)
        for item in references[:remaining]:
            trial = chosen_references + [item]
            if len(self._essential_json(chosen_candidates, trial)) > self.max_total_chars:
                break
            chosen_references = trial
        return chosen_candidates, chosen_references

    def render(self, *, request: Any, global_context: Any, node_context: Any,
               logic_area_context: Any, resource_candidates: Any,
               ootb_reference_cases: Any, site_knowledge_cases: Any,
               candidate_aliases: dict[str, Any], reference_aliases: dict[str, Any]) -> str:
        candidate_rows = [self._candidate_row(alias, item) for alias, item in candidate_aliases.items()]
        reference_rows = [self._reference_row(alias, item) for alias, item in reference_aliases.items()]
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
        if len(text) <= self.max_total_chars:
            return text
        essential = {"request": {"query": str(getattr(request, "query", ""))[:300],
            "top_k": getattr(request, "top_k", 5)}, "resource": candidate_rows,
            "references": reference_rows}
        text = json.dumps(essential, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(text) > self.max_total_chars:
            raise ValueError("essential organizer context exceeds renderer budget")
        return text

    def _essential_json(self, candidates: list[Any], references: list[Any]) -> str:
        value = {"resource": [self._candidate_row(f"c{i:04d}", item) for i, item in enumerate(candidates)],
                 "references": [self._reference_row(f"r{i:04d}", item) for i, item in enumerate(references)]}
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _candidate_row(alias: str, item: Any) -> dict[str, Any]:
        params = []
        for param in list(item.param_list or [])[:6]:
            params.append({"name": str(param.get("param_name") or param.get("name") or "")[:40],
                           "type": str(param.get("data_type_name") or param.get("data_type") or "")[:30]})
        return {"alias": alias, "bo_name": item.bo_name[:80],
            "naming_sql_id": item.naming_sql_id[:80],
            "naming_sql_name": str(item.naming_sql_name or "")[:80],
            "annotation": str(item.annotation or "")[:100], "params": params,
            "return_summary": str(item.return_type or "")[:120],
            "evidence": [str(value)[:80] for value in list(item.evidence or [])[:1]]}

    @staticmethod
    def _reference_row(alias: str, item: Any) -> dict[str, Any]:
        return {"alias": alias, "asset_type": item.asset.asset_type,
                "summary": item.asset.index_text[:100]}

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
