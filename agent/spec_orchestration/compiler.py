from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.environment.environment import FilteredEnvironment
from agent.expression_generation.expression_spec import ExpressionSpec
from agent.resource_manager.loader.namingsql_profile_loader import NamingSqlProfileLoader
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    ContextRegistry,
    FunctionRegistry,
    LocalContextRegistry,
)

from .models import ResolvedGoal, SpecOrchestrationResult


@dataclass(slots=True)
class CompiledResolution:
    expression_spec: ExpressionSpec
    filtered_environment: FilteredEnvironment


class ResolutionCompiler:
    def compile(self, result: SpecOrchestrationResult) -> CompiledResolution:
        resolution = result.root_resolution
        environment = FilteredEnvironment(selection_trace=list(result.resolution_trace))
        if resolution is None:
            return CompiledResolution(
                expression_spec=ExpressionSpec(nl=result.query),
                filtered_environment=environment,
            )

        resolutions = list(_walk(resolution))
        global_contexts: dict[str, ContextRegistry] = {}
        local_contexts: dict[str, LocalContextRegistry] = {}
        functions: dict[str, FunctionRegistry] = {}
        bo_parts: dict[str, dict[str, Any]] = {}
        naming_resolutions = []

        for item in resolutions:
            candidate = item.candidate
            resource = candidate.resource
            if isinstance(resource, LocalContextRegistry):
                local_contexts[resource.resource_id] = resource
            elif isinstance(resource, ContextRegistry):
                global_contexts[resource.resource_id] = resource
            elif isinstance(resource, FunctionRegistry):
                functions[resource.resource_id] = resource
            if candidate.kind in {"bo_field", "relation", "bo_select"}:
                bo = resource if isinstance(resource, BoRegistry) else candidate.metadata.get("bo")
                if isinstance(bo, BoRegistry):
                    part = bo_parts.setdefault(bo.bo_name, {"bo": bo, "fields": {}, "sql": {}})
                    if candidate.kind == "bo_select":
                        selected_field_names = [
                            candidate.metadata.get("target_field_name"),
                            *candidate.metadata.get("condition_fields", []),
                        ]
                        for field_name in selected_field_names:
                            field = next(
                                (
                                    value
                                    for value in bo.property_list
                                    if value.field_name == field_name
                                ),
                                None,
                            )
                            if field is not None:
                                part["fields"][field.field_name] = field
                        continue
                    field = candidate.metadata.get("field")
                    if field is None and candidate.field_name:
                        field = next(
                            (value for value in bo.property_list if value.field_name == candidate.field_name),
                            None,
                        )
                    if field is not None:
                        part["fields"][field.field_name] = field
            if candidate.kind == "naming_sql":
                bo = candidate.metadata.get("bo")
                if isinstance(bo, BoRegistry):
                    part = bo_parts.setdefault(bo.bo_name, {"bo": bo, "fields": {}, "sql": {}})
                    part["sql"][resource.naming_sql_id] = resource
                    naming_resolutions.append(item)

        selected_bos = [
            part["bo"].model_copy(
                update={
                    "property_list": list(part["fields"].values()),
                    "naming_sql_list": list(part["sql"].values()),
                },
                deep=True,
            )
            for part in bo_parts.values()
        ]
        environment.selected_global_contexts = list(global_contexts.values())
        environment.selected_global_context_ids = list(global_contexts)
        environment.visible_local_context = list(local_contexts.values())
        environment.selected_local_context_ids = list(local_contexts)
        environment.selected_functions = list(functions.values())
        environment.selected_function_ids = list(functions)
        environment.selected_bos = selected_bos
        environment.selected_bo_ids = [item.resource_id for item in selected_bos]
        if naming_resolutions:
            environment.naming_sql_selection = _naming_selection(naming_resolutions)

        spec_text = _render_resolution(resolution)
        expression_spec = ExpressionSpec(nl=spec_text)
        return CompiledResolution(
            expression_spec=expression_spec,
            filtered_environment=environment,
        )


def _walk(resolution: ResolvedGoal):
    for dependency in resolution.dependencies:
        yield from _walk(dependency)
    yield resolution


def _render_resolution(root: ResolvedGoal) -> str:
    lines = [
        (
            f"目标“{root.goal.semantic_name}”的最终资源为"
            f"{_candidate_label(root)}。"
        )
    ]
    for item in _walk(root):
        candidate = item.candidate
        if candidate.kind == "context":
            lines.append(
                f"从上下文 {_context_path(candidate.resource)} 获取“{item.goal.semantic_name}”。"
            )
        elif candidate.kind == "literal":
            lines.append(
                f"使用纯字符串“{candidate.metadata.get('value', candidate.resource)}”"
                f"作为“{item.goal.semantic_name}”的值。"
            )
        elif candidate.kind == "naming_sql":
            bindings = []
            by_goal_id = {dep.goal.goal_id: dep for dep in item.dependencies}
            for input_name, goal_id in item.bindings.items():
                dependency = by_goal_id.get(goal_id)
                bindings.append(
                    f"{input_name} 绑定到 {_candidate_label(dependency)}"
                    if dependency is not None
                    else f"{input_name} 绑定到依赖 {goal_id}"
                )
            suffix = "；".join(bindings) if bindings else "无参数"
            lines.append(
                f"使用 NamingSQL {item.candidate.resource.sql_name} 获取"
                f"{item.candidate.bo_name}，{suffix}。"
            )
        elif candidate.kind == "function":
            lines.append(f"调用函数 {_candidate_label(item)} 生成“{item.goal.semantic_name}”。")
        elif candidate.kind == "composition":
            operator = candidate.metadata.get("operator")
            operands = "、".join(
                _candidate_label(dependency) for dependency in item.dependencies
            )
            if operator == "concat":
                lines.append(
                    f"按顺序拼接 {operands}，生成“{item.goal.semantic_name}”。"
                )
            elif operator == "if" and len(item.dependencies) == 3:
                condition, then_value, else_value = item.dependencies
                lines.append(
                    f"如果 {_candidate_label(condition)} 成立，则取 "
                    f"{_candidate_label(then_value)}，否则取"
                    f"{_candidate_label(else_value)}，生成“{item.goal.semantic_name}”。"
                )
        elif candidate.kind == "bo_select":
            bindings = []
            by_goal_id = {dep.goal.goal_id: dep for dep in item.dependencies}
            for field_name, goal_id in item.bindings.items():
                dependency = by_goal_id.get(goal_id)
                bindings.append(
                    f"{field_name} == {_candidate_label(dependency)}"
                    if dependency is not None
                    else f"{field_name} 绑定到依赖 {goal_id}"
                )
            operation = candidate.metadata.get("operation", "select_one")
            target_field = candidate.metadata.get("target_field_name")
            lines.append(
                f"使用 {operation}({candidate.bo_name})，按"
                f"{'，'.join(bindings)} 筛选记录并读取 {target_field}。"
            )
        elif candidate.kind in {"bo_field", "relation"}:
            lines.append(
                f"读取 {candidate.bo_name}.{candidate.field_name} 得到"
                f"“{item.goal.semantic_name}”。"
            )
    lines.append("任一必要中间结果为空时执行项目配置的空值保护或回退策略。")
    return "\n".join(lines)


def _candidate_label(value: ResolvedGoal | None) -> str:
    if value is None:
        return "未知依赖"
    candidate = value.candidate
    if candidate.kind == "context":
        return _context_path(candidate.resource)
    if candidate.kind == "literal":
        return f"纯字符串“{candidate.metadata.get('value', candidate.resource)}”"
    if candidate.kind == "naming_sql":
        return str(candidate.resource.sql_name)
    if candidate.kind == "function":
        return str(candidate.resource.func_name)
    if candidate.kind == "composition":
        if candidate.metadata.get("operator") == "if":
            return "条件表达式"
        return "字符串拼接"
    if candidate.kind == "bo_select":
        return (
            f"{candidate.metadata.get('operation', 'select_one')}"
            f"({candidate.bo_name})"
        )
    if candidate.bo_name and candidate.field_name:
        return f"{candidate.bo_name}.{candidate.field_name}"
    return candidate.candidate_id


def _context_path(resource: Any) -> str:
    if hasattr(resource, "context_name"):
        return str(resource.context_name)
    if isinstance(resource, dict):
        return str(resource.get("path") or resource.get("id") or "context")
    return "context"


def _naming_selection(resolutions: list[ResolvedGoal]) -> list:
    profiles = []
    loader = NamingSqlProfileLoader()
    seen = set()
    for item in resolutions:
        sql = item.candidate.resource
        bo = item.candidate.metadata.get("bo")
        if not isinstance(bo, BoRegistry):
            continue
        for profile in loader.load_bo(bo):
            key = (profile.bo_name, profile.namingsql_name)
            if profile.namingsql_name == sql.sql_name and key not in seen:
                seen.add(key)
                profiles.append(profile)
    return profiles
