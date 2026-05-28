import json
from typing import Any

from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.llm_planner import _summarize_node


class LLMDifficultyRouter:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    @property
    def is_usable(self) -> bool:
        return self.client.is_usable

    def can_plan_with_context_only(self, *, node_info: NodeDef, user_query: str) -> bool:
        if not self.is_usable:
            return False

        try:
            response = generate_by_llm(
                prompt_template="difficulty_router",
                llm_name="base",
                lang="zh",
                client=self.client,
                user_requirement=user_query,
                node_info_json=_dump_json(_summarize_node(node_info)),
            )
        except Exception:
            return False

        return _is_context_only_response(response)


def _is_context_only_response(response: dict[str, Any]) -> bool:
    decision = str(
        response.get("decision")
        or response.get("difficulty")
        or response.get("route")
        or ""
    ).strip().lower()
    if decision in {"context_only", "simple", "easy", "local_global_context"}:
        return True
    if decision in {"resource_filter", "complex", "table_lookup", "need_resources"}:
        return False

    value = response.get("context_only")
    if isinstance(value, bool):
        return value
    value = response.get("can_plan_with_context_only")
    if isinstance(value, bool):
        return value

    return False


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
