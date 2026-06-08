from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from agent.environment.environment import build_filtered_environment
from agent.environment.resource_filter import LLMResourceFilter
from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.generator import generate_expression
from agent.expression_generation.ast.validator import validate_ast
from agent.models import NodeDef, ValueLogicRequest, ValueLogicResult, ValueLogicSource
from agent.planner.difficulty_router import LLMDifficultyRouter, ResourceRoute
from agent.planner.llm_planner import LLMPlanner
from agent.resource_manager.loader.resource_loader import LoadedResource, ResourceLoader, resource_loader as default_resource_loader


DEFAULT_CONTEXT_LIMIT = 5
DEFAULT_RESOURCE_LIMIT = 5
MAX_DYNAMIC_CONTEXT_LIMIT = 12
MAX_DYNAMIC_RESOURCE_LIMIT = 10


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
    ):
        self.resource_loader = resource_loader or default_resource_loader
        self.llm_resource_filter = llm_resource_filter or LLMResourceFilter()
        self.llm_difficulty_router = llm_difficulty_router or LLMDifficultyRouter()
        self.llm_planner = llm_planner or LLMPlanner()

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
        route = self._route_resources(node_info, request.query)
        resource_limits = _resource_limits_from_route(route)
        filtered_env = build_filtered_environment(
            node_info=node_info,
            user_query=request.query,
            registry=ctx.resources.loaded,
            llm_resource_filter=self.llm_resource_filter,
            **resource_limits,
        )
        plan = self.llm_planner.plan(
            node_info=node_info,
            user_query=request.query,
            filtered_env=filtered_env,
        )
        ast = build_ast(plan)
        validate_ast(ast)
        expression = generate_expression(ast)

        return ValueLogicResult(
            node_id=self._node_id(request.node),
            logic_type="expression",
            expression=expression,
            source=ValueLogicSource(source_type="plan")
        )

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

        ab_content = parent_node.get("ab_content")
        if not isinstance(ab_content, dict):
            return None
        data_source = ab_content.get("data_source")
        if not isinstance(data_source, dict):
            return None
        if self._normalize_text(data_source.get("data_source_type")) != "sql":
            return None
        sql_query = data_source.get("sql_query")
        if not isinstance(sql_query, dict):
            return None
        bo_name = sql_query.get("bo_name")
        if bo_name is None or not str(bo_name).strip():
            return None
        return str(bo_name).strip()

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
