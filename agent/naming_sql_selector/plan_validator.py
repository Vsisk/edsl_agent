from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel

from agent.naming_sql_selector.models import NamingSqlSelectResponse
from agent.planner.models import FetchExprPlanNode, FetchOneExprPlanNode, Plan

MAX_PLAN_DEPTH = 100
MAX_VISITED_NODES = 10_000


def validate_naming_sql_plan(plan: Plan, result: NamingSqlSelectResponse) -> None:
    """Constrain fetch nodes to the request's authoritative Top-K candidates."""
    if not result.success or not result.candidates:
        raise ValueError("NAMING_SQL_SELECTION_FAILED")
    permitted = _permitted_candidates(result)
    fetches = [node for node in _walk(plan) if isinstance(node, (FetchExprPlanNode, FetchOneExprPlanNode))]
    if not fetches:
        raise ValueError("NAMING_SQL_NOT_USED")

    by_name: dict[str, list] = {}
    for candidate in permitted:
        name = str(candidate.naming_sql_name or "").strip()
        if name:
            by_name.setdefault(name, []).append(candidate)
    for node in fetches:
        matches = by_name.get(node.name, [])
        if not matches:
            code = "NAMING_SQL_OUTSIDE_CONSTRAINTS" if result.selection_constraints is not None else "NAMING_SQL_OUTSIDE_TOP_K"
            raise ValueError(f"{code} name={_bounded(node.name)}")
        if len(matches) != 1:
            raise ValueError(f"NAMING_SQL_CANDIDATE_AMBIGUOUS name={_bounded(node.name)}")
        allowed_params = {
            str(item.get("param_name") or item.get("name") or "").strip()
            for item in matches[0].param_list if isinstance(item, dict)
        }
        actual_names = [param.name for param in node.params]
        if len(actual_names) != len(set(actual_names)):
            raise ValueError(f"NAMING_SQL_UNKNOWN_PARAM name={_bounded(node.name)}")
        unknown = next((name for name in actual_names if name not in allowed_params), None)
        if unknown is not None:
            raise ValueError(f"NAMING_SQL_UNKNOWN_PARAM name={_bounded(unknown)}")


def _permitted_candidates(result: NamingSqlSelectResponse) -> list:
    constraints = result.selection_constraints
    if constraints is None:
        return list(result.candidates)

    top_ids = {candidate.naming_sql_id for candidate in result.candidates}
    top_bos = {candidate.bo_name for candidate in result.candidates}
    allowed_ids = set(constraints.allowed_naming_sql_ids)
    allowed_bos = set(constraints.allowed_bo_names)
    if (len(allowed_ids) != len(constraints.allowed_naming_sql_ids)
            or len(allowed_bos) != len(constraints.allowed_bo_names)
            or not allowed_ids.issubset(top_ids)
            or not allowed_bos.issubset(top_bos)
            or constraints.max_candidates < 1
            or constraints.max_candidates > len(result.candidates)
            or len(allowed_ids) > constraints.max_candidates):
        raise ValueError("NAMING_SQL_INVALID_CONSTRAINTS")

    permitted = [candidate for candidate in result.candidates
        if (not allowed_ids or candidate.naming_sql_id in allowed_ids)
        and (not allowed_bos or candidate.bo_name in allowed_bos)]
    if not permitted or len(permitted) > constraints.max_candidates:
        raise ValueError("NAMING_SQL_INVALID_CONSTRAINTS")
    return permitted


def _walk(value: object) -> Iterator[BaseModel]:
    stack: list[tuple[object, int, bool]] = [(value, 0, False)]
    active: set[int] = set()
    visited = 0
    while stack:
        current, depth, exiting = stack.pop()
        if exiting:
            active.remove(id(current)); continue
        if not isinstance(current, (BaseModel, list, tuple)):
            continue
        visited += 1
        if depth > MAX_PLAN_DEPTH or visited > MAX_VISITED_NODES or id(current) in active:
            raise ValueError("NAMING_SQL_PLAN_TOO_COMPLEX")
        active.add(id(current)); stack.append((current, depth, True))
        if isinstance(current, BaseModel):
            yield current
            children = [getattr(current, name) for name in type(current).model_fields]
        else:
            children = list(current)
        stack.extend((child, depth + 1, False) for child in reversed(children))


def _bounded(value: str, limit: int = 80) -> str:
    return "".join(ch if ch.isprintable() and ch not in "\r\n" else "?" for ch in str(value))[:limit]
