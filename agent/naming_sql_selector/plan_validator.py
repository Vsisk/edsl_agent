from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel

from agent.naming_sql_selector.models import NamingSqlSelectionResult
from agent.planner.models import (
    ContextPathExprPlanNode,
    FetchExprPlanNode,
    FetchOneExprPlanNode,
    Plan,
)

MAX_PLAN_DEPTH = 100
MAX_VISITED_NODES = 10_000


def validate_naming_sql_plan(plan: Plan, result: NamingSqlSelectionResult) -> None:
    """Reject any planner mutation of an approved NamingSQL selection and bindings."""
    selected = result.selected
    if (
        result.status == "needs_review"
        or selected is None
        or not selected.binding_plan.is_complete
        or bool(selected.binding_plan.unbound_params)
        or bool(selected.binding_plan.ambiguous_params)
    ):
        raise ValueError("NAMING_SQL_REVIEW_REQUIRED")

    expected = selected.binding_plan.bindings
    fetches = [
        node
        for node in _walk(plan)
        if isinstance(node, (FetchExprPlanNode, FetchOneExprPlanNode))
    ]
    if not fetches:
        raise ValueError("NAMING_SQL_NOT_USED")

    for node in fetches:
        if node.name != selected.sql_name:
            raise ValueError(f"NAMING_SQL_RESELECTED name={_bounded(node.name)}")
        actual_names = [param.name for param in node.params]
        expected_names = [binding.param_name for binding in expected]
        if len(actual_names) != len(set(actual_names)) or actual_names != expected_names:
            raise ValueError(f"NAMING_SQL_PARAM_SET_CHANGED params={_bounded(','.join(actual_names))}")
        for param, binding in zip(node.params, expected):
            if not isinstance(param.value, ContextPathExprPlanNode) or param.value.path != binding.source_ref:
                raise ValueError(f"NAMING_SQL_BINDING_CHANGED param={_bounded(param.name)}")


def _walk(value: object) -> Iterator[BaseModel]:
    stack: list[tuple[object, int, bool]] = [(value, 0, False)]
    active: set[int] = set()
    visited = 0
    while stack:
        current, depth, exiting = stack.pop()
        if exiting:
            active.remove(id(current))
            continue
        if not isinstance(current, (BaseModel, list, tuple)):
            continue
        visited += 1
        if depth > MAX_PLAN_DEPTH or visited > MAX_VISITED_NODES or id(current) in active:
            raise ValueError("NAMING_SQL_PLAN_TOO_COMPLEX")
        active.add(id(current))
        stack.append((current, depth, True))
        if isinstance(current, BaseModel):
            yield current
            children = [getattr(current, name) for name in type(current).model_fields]
        else:
            children = list(current)
        stack.extend((child, depth + 1, False) for child in reversed(children))


def _bounded(value: str, limit: int = 80) -> str:
    safe = "".join(ch if ch.isprintable() and ch not in "\r\n" else "?" for ch in str(value))
    return safe[:limit]
