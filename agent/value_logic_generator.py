from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from agent.environment.environment import build_filtered_environment, filter_resources
from agent.environment.resource_filter import LLMResourceFilter, ResourceFilterTargetGenerator
from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.generator import generate_expression
from agent.expression_generation.ast.validator import validate_ast
from agent.models import NodeDef, ValueLogicRequest, ValueLogicResult, ValueLogicSource
from agent.naming_sql_selector import NamingSqlSelectionRequest, NamingSqlSelector, validate_naming_sql_plan
from agent.naming_sql_selector.spec_generator import MAX_AVAILABLE_CONTEXT, requires_naming_sql
from agent.planner.difficulty_router import LLMDifficultyRouter, ResourceRoute
from agent.planner.llm_planner import LLMPlanner
from agent.resource_manager.loader.resource_loader import LoadedResource, ResourceLoader, resource_loader as default_resource_loader


DEFAULT_CONTEXT_LIMIT = 5
DEFAULT_RESOURCE_LIMIT = 5
MAX_DYNAMIC_CONTEXT_LIMIT = 12
MAX_DYNAMIC_RESOURCE_LIMIT = 10


@dataclass(slots=True)
class ExpressionSpec:
    nl: str


class ExpressionSpecGenerator:
    def generate(self, *, request: ValueLogicRequest, node_info: NodeDef) -> ExpressionSpec:
        return ExpressionSpec(nl=str(request.query or "").strip())


@dataclass(slots=True)
class ResourceContext:
    loaded: LoadedResource


@dataclass(slots=True)
class GenerationContext:
    resources: ResourceContext
    node: dict[str, Any]
    parent_node: dict[str, Any] | None
    query: str


class ValueLogicGenerator:
    def __init__(
        self,
        *,
        resource_loader: ResourceLoader | None = None,
        llm_resource_filter: Any | None = None,
        llm_difficulty_router: Any | None = None,
        llm_planner: LLMPlanner | None = None,
        expression_spec_generator: Any | None = None,
        resource_filter_target_generator: Any | None = None,
        enable_legacy_filter_fallback: bool = False,
        naming_sql_selector: NamingSqlSelector | None = None,
    ):
        self.resource_loader = resource_loader or default_resource_loader
        self.llm_resource_filter = llm_resource_filter or LLMResourceFilter()
        self.llm_difficulty_router = llm_difficulty_router or LLMDifficultyRouter()
        self.llm_planner = llm_planner or LLMPlanner()
        self.expression_spec_generator = expression_spec_generator or ExpressionSpecGenerator()
        self.resource_filter_target_generator = resource_filter_target_generator or ResourceFilterTargetGenerator()
        self.enable_legacy_filter_fallback = enable_legacy_filter_fallback
        self.naming_sql_selector = naming_sql_selector or NamingSqlSelector()

    def generate(self, request: ValueLogicRequest) -> ValueLogicResult:
        resources = ResourceContext(
            loaded=self.resource_loader.load_resource(
                request.site_id,
                request.project_id,
                request.edsl_tree,
            )
        )
        ctx = GenerationContext(
            resources=resources,
            node=request.node,
            parent_node=request.parent_node,
            query=request.query,
        )

        if not request.is_ab:
            return self._generate_simple_leaf_expression(request, ctx)
        else:
            return self._generate_field_logic(request, ctx)

    def _load_project_edsl_tree(self) -> dict[str, Any]:
        tree_path = self.resource_loader.data_dir / "edsl_tree.json"
        if not tree_path.exists():
            return {}
        with tree_path.open("r", encoding="utf-8") as tree_file:
            payload = json.load(tree_file)
        if not isinstance(payload, dict):
            raise ValueError(f"EDSL tree resource must contain a JSON object: {tree_path}")
        return payload

    def _is_summary_field(self, node: dict[str, Any]) -> bool:
        if self._normalize_text(node.get("field_type")) == "summary":
            return True
        if self._normalize_summary_type(node.get("summary_type")) is not None:
            return True
        summary = node.get("summary") or node.get("summary_config")
        return isinstance(summary, dict)

    def _generate_simple_leaf_expression(
        self,
        request: ValueLogicRequest,
        ctx: GenerationContext,
    ) -> ValueLogicResult:
        return self._generate_expression_by_plan(request, ctx)

    def _generate_field_logic(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        if self._is_summary_field(request.node):
            return self._generate_summary_field_logic(request, ctx)

        return self._generate_normal_field_logic(request, ctx)

    def _generate_summary_field_logic(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        summary_type = self._extract_summary_type(request.node)
        detail_field = self._extract_detail_field(request.node)

        return ValueLogicResult(
            node_id=self._node_id(request.node),
            logic_type="summary",
            expression=None,
            source=ValueLogicSource(
                source_type="detail_field",
                detail_field=detail_field,
                summary_type=summary_type,
            )
        )

    def _generate_normal_field_logic(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        if request.parent_node :
            if self._is_sql_source(request.parent_node):
                bo_name = self._extract_parent_sql_bo_name(request.parent_node)
                mapping_result = self._try_generate_bo_field_mapping(request, ctx, bo_name)
                if mapping_result is not None:
                    return mapping_result
                return self._generate_expression_by_plan(request, ctx)

            return self._generate_expression_by_plan(request, ctx)

        return self._generate_expression_by_plan(request, ctx)

    def _try_generate_bo_field_mapping(
        self,
        request: ValueLogicRequest,
        ctx: GenerationContext,
        bo_name: str | None,
    ) -> ValueLogicResult | None:
        if not self._should_try_bo_field_mapping(request):
            return None

        if not bo_name:
            return None

        bo_registry = ctx.resources.loaded.bo_registry.get(bo_name)
        if bo_registry is None:
            return None

        target_field_name = self._node_name(request.node)
        if not target_field_name:
            return None

        for bo_property in bo_registry.property_list:
            bo_field = bo_property.field_name
            if self._normalize_field_name(bo_field) == self._normalize_field_name(target_field_name):
                return ValueLogicResult(
                    node_id=self._node_id(request.node),
                    logic_type="bo_field_mapping",
                    expression=bo_field,
                    source=ValueLogicSource(
                        source_type="bo",
                        bo_name=bo_name,
                        bo_field=bo_field,
                    ),
                )

        return None

    def _generate_expression_by_plan(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        node_info = self._to_node_def(request.node, request.node_path)
        resource_limits = _default_resource_limits()
        expression_spec = self.expression_spec_generator.generate(
            request=request,
            node_info=node_info,
        )
        targets = self.resource_filter_target_generator.generate(
            query=expression_spec.nl,
            domain_registry=ctx.resources.loaded.domain_registry,
            resource_count_summary=_resource_count_summary(ctx.resources.loaded),
        )
        filtered_env = filter_resources(
            targets=targets,
            loaded_resource=ctx.resources.loaded,
            resource_limits=resource_limits,
        )
        if not targets and self.enable_legacy_filter_fallback:
            route = self._route_resources(node_info, expression_spec.nl)
            legacy_limits = _resource_limits_from_route(route)
            filtered_env = build_filtered_environment(
                node_info=node_info,
                user_query=expression_spec.nl,
                registry=ctx.resources.loaded,
                llm_resource_filter=self.llm_resource_filter,
                **legacy_limits,
            )
        naming_sql_selection = None
        if requires_naming_sql(
            request.structured_spec, request.query, expression_spec.nl, request.node, request.parent_node
        ):
            selection_request = NamingSqlSelectionRequest(
                site_id=request.site_id,
                query=request.query or expression_spec.nl,
                node=request.node,
                parent_node=request.parent_node,
                structured_spec=request.structured_spec,
                bo_name=self._requested_bo_name(request),
                available_context=self._available_context(filtered_env, ctx.resources.loaded, request.node_path),
            )
            naming_sql_selection = self.naming_sql_selector.select(
                selection_request,
                loaded_resource=ctx.resources.loaded,
            )
            if naming_sql_selection is None or naming_sql_selection.status == "needs_review" or naming_sql_selection.selected is None:
                raise ValueError("NAMING_SQL_REVIEW_REQUIRED")
            filtered_env = self._narrow_naming_sql_environment(
                filtered_env, ctx.resources.loaded, request.node_path, naming_sql_selection
            )
        plan = self.llm_planner.plan(
            node_info=node_info,
            user_query=request.query,
            filtered_env=filtered_env,
        )
        if naming_sql_selection is not None:
            validate_naming_sql_plan(plan, naming_sql_selection)
        ast = build_ast(plan)
        validate_ast(ast)
        expression = generate_expression(ast)

        return ValueLogicResult(
            node_id=self._node_id(request.node),
            logic_type="expression",
            expression=expression,
            source=ValueLogicSource(source_type="plan")
        )

    def _requested_bo_name(self, request: ValueLogicRequest) -> str | None:
        value = request.structured_spec.get("bo_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return self._extract_parent_sql_bo_name(request.parent_node)

    def _available_context(self, env, loaded: LoadedResource, node_path: str) -> list[dict[str, Any]]:
        visible_local = list(loaded.get_visible_local_context_registry(node_path).values())
        ordered = [
            *env.selected_global_contexts,
            *env.visible_local_context,
            *visible_local,
            *loaded.context_registry.values(),
        ]
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for context in ordered:
            source_ref = str(getattr(context, "context_name", "") or "")
            if not source_ref or source_ref in seen:
                continue
            seen.add(source_ref)
            return_type = getattr(context, "return_type", None)
            concrete_type = str(
                getattr(return_type, "data_type_name", None)
                or getattr(return_type, "data_type", "")
                or ""
            )
            result.append({
                "name": source_ref.rsplit(".", 1)[-1],
                "source_ref": source_ref,
                "data_type": concrete_type,
                "is_list": bool(getattr(return_type, "is_list", False)),
                "semantic_tags": list(getattr(context, "tag", []) or []),
            })
            if len(result) >= MAX_AVAILABLE_CONTEXT:
                break
        return result

    def _narrow_naming_sql_environment(self, env, loaded: LoadedResource, node_path: str, selection):
        selected = selection.selected
        bo = next((item for item in loaded.bo_registry.values() if item.bo_name == selection.selected_bo), None)
        if bo is None or selected is None:
            raise ValueError("NAMING_SQL_REVIEW_REQUIRED")
        if selected.naming_sql_id:
            matches = [item for item in bo.naming_sql_list if item.naming_sql_id == selected.naming_sql_id]
            if len(matches) > 1:
                raise ValueError(f"NAMING_SQL_DEFINITION_AMBIGUOUS id={str(selected.naming_sql_id)[:80]}")
            definition = matches[0] if len(matches) == 1 and matches[0].sql_name == selected.sql_name else None
        else:
            matches = [item for item in bo.naming_sql_list if item.sql_name == selected.sql_name]
            if len(matches) > 1:
                raise ValueError(f"NAMING_SQL_DEFINITION_AMBIGUOUS name={str(selected.sql_name)[:80]}")
            definition = matches[0] if len(matches) == 1 else None
        if definition is None:
            raise ValueError(
                f"NAMING_SQL_DEFINITION_NOT_LOADED id={str(selected.naming_sql_id)[:80]} name={str(selected.sql_name)[:80]}"
            )

        global_by_ref = {item.context_name: item for item in loaded.context_registry.values()}
        local_by_ref = {item.context_name: item for item in loaded.get_visible_local_context_registry(node_path).values()}
        globals_out = list(env.selected_global_contexts)
        locals_out = list(env.visible_local_context)
        global_seen = {item.context_name for item in globals_out}
        local_seen = {item.context_name for item in locals_out}
        for binding in selected.binding_plan.bindings:
            source_ref = binding.source_ref
            if source_ref in global_by_ref:
                if source_ref not in global_seen:
                    globals_out.append(global_by_ref[source_ref]); global_seen.add(source_ref)
            elif source_ref in local_by_ref:
                if source_ref not in local_seen:
                    locals_out.append(local_by_ref[source_ref]); local_seen.add(source_ref)
            else:
                raise ValueError(f"NAMING_SQL_BINDING_SOURCE_NOT_LOADED source_ref={source_ref}")
        narrowed_bo = bo.model_copy(update={"naming_sql_list": [definition]}, deep=True)
        env.selected_bos = [narrowed_bo]
        env.selected_bo_ids = [narrowed_bo.resource_id]
        env.selected_global_contexts = globals_out
        env.selected_global_context_ids = [item.resource_id for item in globals_out]
        env.visible_local_context = locals_out
        env.selected_local_context_ids = [item.resource_id for item in locals_out]
        env.naming_sql_selection = selection
        return env

    def _route_resources(self, node_info: NodeDef, user_query: str) -> ResourceRoute:
        try:
            route = self.llm_difficulty_router.route_resources(
                node_info=node_info,
                user_query=user_query,
            )
            return ResourceRoute(
                use_bo=bool(getattr(route, "use_bo", True)),
                use_function=bool(getattr(route, "use_function", True)),
                resource_count_hint=getattr(route, "resource_count_hint", DEFAULT_RESOURCE_LIMIT),
            )
        except Exception:
            return ResourceRoute()

    def _to_node_def(self, node: dict[str, Any], node_path: str) -> NodeDef:
        return NodeDef(
            node_id=self._node_id(node) or "",
            node_path=node_path,
            node_name=self._node_name(node),
            description=str(node.get("description") or node.get("annotation") or ""),
            is_ab=bool(node.get("is_ab"))
        )

    def _is_sql_source(self, parent_node: dict[str, Any]) -> bool:
        source_values = [
            parent_node.get("source_type"),
            parent_node.get("data_source_type"),
        ]
        ab_data_source = parent_node.get("ab_data_source")
        if isinstance(ab_data_source, dict):
            source_values.extend(
                [
                    ab_data_source.get("source_type"),
                    ab_data_source.get("data_source_type"),
                ]
            )
        data_source = parent_node.get("data_source")
        if isinstance(data_source, dict):
            source_values.extend(
                [
                    data_source.get("source_type"),
                    data_source.get("data_source_type"),
                ]
            )
        ab_content = parent_node.get("ab_content")
        if isinstance(ab_content, dict):
            ab_data_source = ab_content.get("data_source")
            if isinstance(ab_data_source, dict):
                source_values.extend(
                    [
                        ab_data_source.get("source_type"),
                        ab_data_source.get("data_source_type"),
                    ]
                )
        return any(self._normalize_text(value) == "sql" for value in source_values)

    def _extract_parent_sql_bo_name(self, parent_node: dict[str, Any] | None) -> str | None:
        if not parent_node or not self._is_sql_source(parent_node):
            return None
        containers: list[dict[str, Any]] = [parent_node]
        for key in ("data_source", "ab_data_source"):
            value = parent_node.get(key)
            if isinstance(value, dict):
                containers.append(value)
        ab_content = parent_node.get("ab_content")
        if isinstance(ab_content, dict) and isinstance(ab_content.get("data_source"), dict):
            containers.append(ab_content["data_source"])
        for container in containers:
            source_type = self._normalize_text(container.get("source_type") or container.get("data_source_type"))
            if source_type != "sql":
                continue
            sql_query = container.get("sql_query")
            candidates = [container.get("bo_name")]
            if isinstance(sql_query, dict):
                candidates.insert(0, sql_query.get("bo_name"))
            for bo_name in candidates:
                if isinstance(bo_name, str) and bo_name.strip():
                    return bo_name.strip()
        return None

    def _extract_summary_type(self, node: dict[str, Any]) -> str | None:
        summary = node.get("summary") or node.get("summary_config")
        candidates = [node.get("summary_type"), node.get("aggregate_type"), node.get("aggregation")]
        if isinstance(summary, dict):
            candidates.extend([summary.get("summary_type"), summary.get("type"), summary.get("aggregation")])
        for candidate in candidates:
            normalized = self._normalize_summary_type(candidate)
            if normalized is not None:
                return normalized
        return None

    def _extract_detail_field(self, node: dict[str, Any]) -> str | None:
        summary = node.get("summary") or node.get("summary_config")
        candidates = [node.get("detail_field"), node.get("detail_field_name"), node.get("source_field")]
        if isinstance(summary, dict):
            candidates.extend([summary.get("detail_field"), summary.get("detail_field_name"), summary.get("source_field")])
        for candidate in candidates:
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
        return None

    def _normalize_summary_type(self, value: Any) -> str | None:
        normalized = self._normalize_text(value)
        if normalized in {"sum", "count"}:
            return normalized
        return None

    def _node_type(self, node: dict[str, Any]) -> str:
        return self._normalize_text(node.get("tree_node_type") or node.get("node_type") or node.get("type"))

    def _node_id(self, node: dict[str, Any]) -> str | None:
        for key in ("node_id", "id", "field_id"):
            value = node.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    def _node_name(self, node: dict[str, Any]) -> str:
        for key in ("node_name", "field_name", "name"):
            value = node.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        xml_name_property = node.get("xml_name_property")
        if isinstance(xml_name_property, dict):
            xml_name = xml_name_property.get("xml_name")
            if xml_name is not None and str(xml_name).strip():
                return str(xml_name).strip()
        return self._node_id(node) or ""

    def _normalize_text(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _normalize_field_name(self, value: Any) -> str:
        return self._normalize_text(value).replace("_", "")

    def _should_try_bo_field_mapping(self, request: ValueLogicRequest) -> bool:
        query = self._normalize_text(request.query)
        if not query:
            return False

        expression_intent_terms = (
            "derive",
            "calculate",
            "compute",
            "format",
            "fallback",
            "default",
            "mask",
            "concat",
            "combine",
            "if ",
            "when ",
            "判断",
            "计算",
            "加工",
            "格式",
            "默认",
            "拼接",
            "掩码",
            "脱敏",
        )
        if any(term in query for term in expression_intent_terms):
            return False

        mapping_intent_terms = (
            "direct",
            "directly",
            "map",
            "mapping",
            "table field",
            "bo field",
            "field mapping",
            "字段映射",
            "直接取",
            "直接映射",
            "取字段",
            "表字段",
        )
        return any(term in query for term in mapping_intent_terms)


def _clamp_limit(value: Any, *, default: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    if normalized < default:
        return default
    return min(normalized, maximum)


def _resource_limits_from_route(route: ResourceRoute) -> dict[str, int]:
    context_limit = _clamp_limit(
        getattr(route, "resource_count_hint", DEFAULT_CONTEXT_LIMIT),
        default=DEFAULT_CONTEXT_LIMIT,
        maximum=MAX_DYNAMIC_CONTEXT_LIMIT,
    )
    resource_limit = _clamp_limit(
        getattr(route, "resource_count_hint", DEFAULT_RESOURCE_LIMIT),
        default=DEFAULT_RESOURCE_LIMIT,
        maximum=MAX_DYNAMIC_RESOURCE_LIMIT,
    )
    return {
        "top_global_context": context_limit,
        "top_local_context": context_limit,
        "top_bo": resource_limit if route.use_bo else 0,
        "top_function": resource_limit if route.use_function else 0,
    }


def _default_resource_limits() -> dict[str, int]:
    return {
        "context_count": DEFAULT_CONTEXT_LIMIT,
        "bo_count": DEFAULT_RESOURCE_LIMIT,
        "function_count": DEFAULT_RESOURCE_LIMIT,
        "namingsql_count": DEFAULT_RESOURCE_LIMIT,
    }


def _resource_count_summary(loaded_resource: LoadedResource) -> dict[str, int]:
    return {
        "context_count": len(loaded_resource.context_registry),
        "bo_count": len(loaded_resource.bo_registry),
        "function_count": len(loaded_resource.function_registry),
        "namingsql_count": sum(
            len(getattr(bo, "naming_sql_list", []) or []) for bo in loaded_resource.bo_registry.values()
        ),
    }
