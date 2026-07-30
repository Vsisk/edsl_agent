from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.resource_manager.loader.registry_models import ReturnType

from .models import (
    BO_ACCESS_TIER_ORDER,
    CoverageKind,
    GoalRole,
    GoalSearchRequest,
    GoalStatus,
    OperandKind,
    QueryDecomposition,
    QueryPlanKind,
    ResolvedGoal,
    ResourceCandidate,
    ResourceTier,
    SpecOrchestrationResult,
    VALUE_GOAL_TIER_ORDER,
    ValueGoal,
)


class SpecOrchestrator:
    def __init__(
        self,
        *,
        semantic: Any,
        search: Any,
        max_depth: int = 6,
        max_goals: int = 20,
        max_parallel_goals: int = 4,
    ) -> None:
        self.semantic = semantic
        self.search = search
        self.max_depth = max_depth
        self.max_goals = max_goals
        self.max_parallel_goals = max_parallel_goals

    def resolve(
        self,
        *,
        node_info: Any,
        query: str,
        expected_type: ReturnType,
        request: Any | None = None,
        context_pack: Any | None = None,
        node_path: str = "",
    ) -> SpecOrchestrationResult:
        if hasattr(self.semantic, "configure_background"):
            self.semantic.configure_background(
                request=request,
                context_pack=context_pack,
            )
        decomposition = (
            self.semantic.decompose_query(
                node_info=node_info,
                query=query,
                expected_type=expected_type,
            )
            if hasattr(self.semantic, "decompose_query")
            else QueryDecomposition(kind=QueryPlanKind.SINGLE)
        )
        if decomposition.kind == QueryPlanKind.LITERAL:
            root, resolution = _literal_resolution(
                goal_id="root",
                value=decomposition.literal_value or "",
                role=GoalRole.FINAL_OUTPUT,
                expected_type=expected_type,
            )
            return SpecOrchestrationResult(
                query=query,
                root_goal=root,
                root_resolution=resolution,
                execution_order=["root"],
            )
        if decomposition.kind == QueryPlanKind.COMPOSE:
            return self._resolve_composition(
                decomposition=decomposition,
                query=query,
                expected_type=expected_type,
                node_path=node_path,
            )
        root = self.semantic.generate_goal(
            goal_id="root",
            node_info=node_info,
            query=query,
            expected_type=expected_type,
            role=GoalRole.FINAL_OUTPUT,
        )
        state = _ResolutionState(max_goals=self.max_goals)
        resolution = self._resolve_goal(
            root,
            query=query,
            node_path=node_path,
            depth=0,
            stack=(),
            state=state,
            tiers=VALUE_GOAL_TIER_ORDER,
        )
        if resolution is None:
            root.status = GoalStatus.FAILED
            state.failed_goal_ids.append(root.goal_id)
        return SpecOrchestrationResult(
            query=query,
            root_goal=root,
            root_resolution=resolution,
            execution_order=_execution_order(resolution),
            failed_goal_ids=list(dict.fromkeys(state.failed_goal_ids)),
            resolution_trace=state.trace,
        )

    def _resolve_composition(
        self,
        *,
        decomposition: QueryDecomposition,
        query: str,
        expected_type: ReturnType,
        node_path: str,
    ) -> SpecOrchestrationResult:
        root = ValueGoal(
            goal_id="root",
            semantic_name=query,
            role=GoalRole.FINAL_OUTPUT,
            expected_type=expected_type.model_copy(deep=True),
            status=GoalStatus.WAITING_DEPENDENCIES,
        )
        dependencies: list[ResolvedGoal | None] = [None] * len(decomposition.operands)
        branch_states: dict[int, _ResolutionState] = {}
        resource_indexes = [
            index
            for index, operand in enumerate(decomposition.operands)
            if operand.kind == OperandKind.RESOURCE
        ]
        for index, operand in enumerate(decomposition.operands):
            if operand.kind == OperandKind.LITERAL:
                operand_type = _composition_operand_type(
                    decomposition=decomposition,
                    index=index,
                    result_type=expected_type,
                )
                _, dependencies[index] = _literal_resolution(
                    goal_id=f"root::operand:{index}",
                    value=operand.value or "",
                    role=GoalRole.INTERMEDIATE_VALUE,
                    expected_type=operand_type,
                )

        def resolve_operand(index: int) -> tuple[int, ResolvedGoal | None, _ResolutionState]:
            operand = decomposition.operands[index]
            state = _ResolutionState(max_goals=self.max_goals)
            goal = ValueGoal(
                goal_id=f"root::operand:{index}",
                semantic_name=operand.semantic_name or "",
                role=GoalRole.INTERMEDIATE_VALUE,
                expected_type=_composition_operand_type(
                    decomposition=decomposition,
                    index=index,
                    result_type=expected_type,
                ),
            )
            resolution = self._resolve_goal(
                goal,
                query=query,
                node_path=node_path,
                depth=1,
                stack=(),
                state=state,
                tiers=VALUE_GOAL_TIER_ORDER,
            )
            return index, resolution, state

        with ThreadPoolExecutor(
            max_workers=min(self.max_parallel_goals, len(resource_indexes))
        ) as executor:
            futures = [executor.submit(resolve_operand, index) for index in resource_indexes]
            for future in futures:
                index, resolution, branch_state = future.result()
                dependencies[index] = resolution
                branch_states[index] = branch_state

        trace = []
        failed_goal_ids = []
        for index in resource_indexes:
            branch_state = branch_states[index]
            trace.extend(branch_state.trace)
            failed_goal_ids.extend(branch_state.failed_goal_ids)
        if any(item is None for item in dependencies):
            root.status = GoalStatus.FAILED
            failed_goal_ids.append(root.goal_id)
            return SpecOrchestrationResult(
                query=query,
                root_goal=root,
                failed_goal_ids=list(dict.fromkeys(failed_goal_ids)),
                resolution_trace=trace,
            )
        committed = [item for item in dependencies if item is not None]
        root.status = GoalStatus.RESOLVED
        candidate = ResourceCandidate(
            candidate_id="composition:root",
            kind="composition",
            resource={"operator": decomposition.operator},
            return_type=expected_type.model_copy(deep=True),
            metadata={"operator": decomposition.operator},
        )
        root.selected_candidate_id = candidate.candidate_id
        root.candidate_resolutions = [candidate]
        resolution = ResolvedGoal(
            goal=root,
            candidate=candidate,
            dependencies=committed,
            bindings={
                str(index): dependency.goal.goal_id
                for index, dependency in enumerate(committed)
            },
        )
        return SpecOrchestrationResult(
            query=query,
            root_goal=root,
            root_resolution=resolution,
            execution_order=_execution_order(resolution),
            failed_goal_ids=list(dict.fromkeys(failed_goal_ids)),
            resolution_trace=trace,
        )

    def _resolve_goal(
        self,
        goal: ValueGoal,
        *,
        query: str,
        node_path: str,
        depth: int,
        stack: tuple[tuple[str, str, bool], ...],
        state: "_ResolutionState",
        tiers: tuple[ResourceTier, ...],
    ) -> ResolvedGoal | None:
        signature = _goal_signature(goal)
        if (
            depth > self.max_depth
            or state.goal_count >= state.max_goals
            or signature in stack
        ):
            state.failed_goal_ids.append(goal.goal_id)
            state.trace.append({"goal_id": goal.goal_id, "action": "budget_or_cycle"})
            return None
        state.goal_count += 1
        goal.status = GoalStatus.SEARCHING
        next_stack = (*stack, signature)
        keyword_decision = self.semantic.generate_keywords(
            goal=goal, query=query
        )
        for tier in tiers:
            goal.current_tier = tier
            request = GoalSearchRequest(
                goal=goal,
                tier=tier,
                keywords=keyword_decision.keywords,
                aliases=keyword_decision.aliases,
                negative_keywords=keyword_decision.negative_keywords,
                target_bo_name=goal.target_bo_name,
                target_field_name=goal.target_field_name,
                query=query,
                node_path=node_path,
            )
            recalled = self.search.search(request)
            candidates = [
                item for item in recalled
                if _types_compatible(goal.expected_type, item.return_type)
            ]
            state.trace.append(
                {
                    "goal_id": goal.goal_id,
                    "tier": tier.value,
                    "action": "search",
                    "recalled": len(recalled),
                    "validated": len(candidates),
                }
            )
            if not candidates:
                continue
            remaining = list(candidates)
            while remaining:
                decision = self.semantic.decide_coverage(
                    goal=goal,
                    tier=tier,
                    candidates=remaining,
                    query=query,
                )
                if decision.kind == CoverageKind.NOT_COVER:
                    break
                candidate = next(
                    (
                        item for item in remaining
                        if item.candidate_id == decision.selected_candidate_id
                    ),
                    None,
                )
                if candidate is None:
                    break
                resolved = self._resolve_candidate_dependencies(
                    goal,
                    candidate,
                    query=query,
                    node_path=node_path,
                    depth=depth,
                    stack=next_stack,
                    state=state,
                )
                if resolved is not None:
                    goal.status = GoalStatus.RESOLVED
                    goal.selected_candidate_id = candidate.candidate_id
                    goal.candidate_resolutions = [candidate]
                    state.trace.append(
                        {
                            "goal_id": goal.goal_id,
                            "tier": tier.value,
                            "action": "commit",
                            "candidate_id": candidate.candidate_id,
                        }
                    )
                    return resolved
                state.trace.append(
                    {
                        "goal_id": goal.goal_id,
                        "tier": tier.value,
                        "action": "rollback",
                        "candidate_id": candidate.candidate_id,
                    }
                )
                remaining = [
                    item for item in remaining
                    if item.candidate_id != candidate.candidate_id
                ]
        goal.status = GoalStatus.FAILED
        state.failed_goal_ids.append(goal.goal_id)
        return None

    def _resolve_candidate_dependencies(
        self,
        goal: ValueGoal,
        candidate: ResourceCandidate,
        *,
        query: str,
        node_path: str,
        depth: int,
        stack: tuple[tuple[str, str, bool], ...],
        state: "_ResolutionState",
    ) -> ResolvedGoal | None:
        dependencies = []
        bindings = {}
        if candidate.kind in {"bo_field", "relation"} and candidate.bo_name:
            bo_goal = ValueGoal(
                goal_id=f"{goal.goal_id}::__bo__:{candidate.bo_name}",
                semantic_name=candidate.bo_name,
                role=GoalRole.INTERMEDIATE_VALUE,
                expected_type=ReturnType(
                    data_type="bo",
                    data_type_name=candidate.bo_name,
                    is_list=False,
                ),
                target_bo_name=candidate.bo_name,
                target_field_name=candidate.field_name,
            )
            resolved_bo = self._resolve_goal(
                bo_goal,
                query=query,
                node_path=node_path,
                depth=depth + 1,
                stack=stack,
                state=state,
                tiers=BO_ACCESS_TIER_ORDER,
            )
            if resolved_bo is None:
                return None
            dependencies.append(resolved_bo)
            bindings["__bo__"] = bo_goal.goal_id
        if not candidate.required_inputs:
            return ResolvedGoal(
                goal=goal,
                candidate=candidate,
                dependencies=dependencies,
                bindings=bindings,
            )
        goal.status = GoalStatus.WAITING_DEPENDENCIES
        for item in candidate.required_inputs:
            dependency = ValueGoal(
                goal_id=f"{goal.goal_id}::{item.name}",
                semantic_name=item.name,
                role=(
                    GoalRole.QUERY_PARAM
                    if candidate.kind == "naming_sql"
                    else GoalRole.FILTER_VALUE
                    if candidate.kind == "bo_select"
                    else GoalRole.FUNCTION_PARAM
                ),
                expected_type=item.return_type.model_copy(deep=True),
            )
            goal.depends_on.append(dependency.goal_id)
            resolved = self._resolve_goal(
                dependency,
                query=query,
                node_path=node_path,
                depth=depth + 1,
                stack=stack,
                state=state,
                tiers=VALUE_GOAL_TIER_ORDER,
            )
            if resolved is None:
                return None
            dependencies.append(resolved)
            bindings[item.name] = dependency.goal_id
        return ResolvedGoal(
            goal=goal,
            candidate=candidate,
            dependencies=dependencies,
            bindings=bindings,
        )


class _ResolutionState:
    def __init__(self, *, max_goals: int) -> None:
        self.max_goals = max_goals
        self.goal_count = 0
        self.failed_goal_ids: list[str] = []
        self.trace: list[dict[str, Any]] = []


def _literal_resolution(
    *,
    goal_id: str,
    value: str,
    role: GoalRole,
    expected_type: ReturnType,
) -> tuple[ValueGoal, ResolvedGoal]:
    goal = ValueGoal(
        goal_id=goal_id,
        semantic_name=value,
        role=role,
        expected_type=expected_type.model_copy(deep=True),
        status=GoalStatus.RESOLVED,
    )
    candidate = ResourceCandidate(
        candidate_id=f"literal:{goal_id}",
        kind="literal",
        resource=value,
        return_type=expected_type.model_copy(deep=True),
        evidence=["query decomposition literal"],
        metadata={"value": value},
    )
    goal.selected_candidate_id = candidate.candidate_id
    goal.candidate_resolutions = [candidate]
    return goal, ResolvedGoal(goal=goal, candidate=candidate)


def _composition_operand_type(
    *,
    decomposition: QueryDecomposition,
    index: int,
    result_type: ReturnType,
) -> ReturnType:
    if decomposition.operator == "if":
        if index == 0:
            return ReturnType(
                data_type="basic",
                data_type_name="boolean",
                is_list=False,
            )
        return result_type.model_copy(deep=True)
    return ReturnType(
        data_type="basic",
        data_type_name="string",
        is_list=False,
    )


def _types_compatible(expected: ReturnType, actual: ReturnType) -> bool:
    if bool(expected.is_list) != bool(actual.is_list):
        return False
    expected_name = str(expected.data_type_name or "").lower()
    actual_name = str(actual.data_type_name or "").lower()
    if expected_name and actual_name and expected_name != actual_name:
        return False
    expected_kind = str(expected.data_type or "").lower()
    actual_kind = str(actual.data_type or "").lower()
    return (
        expected_kind == actual_kind
        or {expected_kind, actual_kind} <= {"key", "basic"}
    )


def _goal_signature(goal: ValueGoal) -> tuple[str, str, bool]:
    return (
        goal.semantic_name.strip().lower(),
        str(goal.expected_type.data_type_name or "").lower(),
        bool(goal.expected_type.is_list),
    )


def _execution_order(resolution: ResolvedGoal | None) -> list[str]:
    if resolution is None:
        return []
    result = []
    for dependency in resolution.dependencies:
        result.extend(_execution_order(dependency))
    result.append(resolution.goal.goal_id)
    return result
