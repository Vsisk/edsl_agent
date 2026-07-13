from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient


@dataclass(frozen=True, slots=True)
class ContextResourceRoute:
    use_current_tree: bool
    fallback: bool = False


class FastContextResourceRouter:
    def __init__(self, client: LLMClient | None = None,
                 decision_fn: Callable[..., Any] = generate_by_llm) -> None:
        self.client = client or LLMClient()
        self.decision_fn = decision_fn

    def route(self, *, query: str, node: dict[str, Any],
              parent_node: dict[str, Any] | None) -> ContextResourceRoute:
        if not self.client.is_usable:
            return ContextResourceRoute(use_current_tree=True, fallback=True)
        try:
            response = self.decision_fn(
                prompt_template="context_resource_router",
                llm_name="base",
                lang="zh",
                client=self.client,
                user_requirement=str(query or "")[:4000],
                node_info_json=self._node_json(node),
                parent_node_info_json=self._node_json(parent_node or {}),
            )
        except Exception:
            return ContextResourceRoute(use_current_tree=True, fallback=True)
        if not isinstance(response, dict) or type(response.get("use_current_tree")) is not bool:
            return ContextResourceRoute(use_current_tree=True, fallback=True)
        return ContextResourceRoute(use_current_tree=response["use_current_tree"])

    @staticmethod
    def _node_json(node: dict[str, Any]) -> str:
        value = {
            "node_id": node.get("node_id") or node.get("id"),
            "name": node.get("name") or node.get("node_name"),
            "type": node.get("tree_node_type") or node.get("type"),
            "annotation": node.get("annotation") or node.get("description"),
        }
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
