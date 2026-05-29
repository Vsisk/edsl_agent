import json
from dataclasses import dataclass
from typing import Any

from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.llm_planner import _summarize_node


@dataclass(frozen=True, slots=True)
class ResourceRoute:
    use_bo: bool = True
    use_function: bool = True


class LLMDifficultyRouter:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    @property
    def is_usable(self) -> bool:
        return self.client.is_usable

    def route_resources(self, *, node_info: NodeDef, user_query: str) -> ResourceRoute:
        if not self.is_usable:
            return ResourceRoute()

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
            return ResourceRoute()

        return _route_from_response(response)

    def can_plan_with_context_only(self, *, node_info: NodeDef, user_query: str) -> bool:
        route = self.route_resources(node_info=node_info, user_query=user_query)
        return not route.use_bo and not route.use_function


def _route_from_response(response: dict[str, Any]) -> ResourceRoute:
    decision = str(
        response.get("decision")
        or response.get("difficulty")
        or response.get("route")
        or ""
    ).strip().lower()
    if decision in {"context_only", "simple", "easy", "local_global_context", "context"}:
        return ResourceRoute(use_bo=False, use_function=False)
    if decision in {"bo_only", "bo", "table_lookup", "need_bo"}:
        return ResourceRoute(use_bo=True, use_function=False)
    if decision in {"function_only", "function", "func_only", "func", "need_function"}:
        return ResourceRoute(use_bo=False, use_function=True)
    if decision in {"resource_filter", "complex", "full", "all", "need_resources", "bo_function"}:
        return ResourceRoute()

    required_resources = _normalize_required_resources(response.get("required_resources"))
    if required_resources:
        return ResourceRoute(
            use_bo=bool({"bo", "table"} & required_resources),
            use_function=bool({"function", "func"} & required_resources),
        )

    value = response.get("context_only")
    if isinstance(value, bool):
        return ResourceRoute(use_bo=not value, use_function=not value)
    value = response.get("can_plan_with_context_only")
    if isinstance(value, bool):
        return ResourceRoute(use_bo=not value, use_function=not value)

    use_bo = response.get("use_bo")
    use_function = response.get("use_function")
    if isinstance(use_bo, bool) or isinstance(use_function, bool):
        return ResourceRoute(
            use_bo=True if use_bo is None else bool(use_bo),
            use_function=True if use_function is None else bool(use_function),
        )

    return ResourceRoute()


def _normalize_required_resources(value: Any) -> set[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return set()

    normalized = {str(item).strip().lower() for item in items if str(item).strip()}
    if "ctx" in normalized:
        normalized.add("context")
    if "local_context" in normalized or "global_context" in normalized:
        normalized.add("context")
    if "functions" in normalized:
        normalized.add("function")
    if "table" in normalized or "tables" in normalized:
        normalized.add("bo")
    return normalized


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
