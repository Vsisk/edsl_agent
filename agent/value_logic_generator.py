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
from agent.planner.llm_planner import LLMPlanner
from agent.resource_manager.loader.resource_loader import LoadedResource, ResourceLoader, resource_loader as default_resource_loader


@dataclass(slots=True)
class ResourceContext:
    loaded: LoadedResource


@dataclass(slots=True)
class GenerationContext:
    resources: ResourceContext
    local_ctx: list[dict[str, Any]]
    node: dict[str, Any]
    parent_node: dict[str, Any] | None
    query: str
    diagnostics: list[str] = field(default_factory=list)


class ValueLogicGenerator:
    def __init__(
        self,
        *,
        resource_loader: ResourceLoader | None = None,
        llm_resource_filter: Any | None = None,
        llm_planner: LLMPlanner | None = None,
    ):
        self.resource_loader = resource_loader or default_resource_loader
        self.llm_resource_filter = llm_resource_filter or LLMResourceFilter()
        self.llm_planner = llm_planner or LLMPlanner()

    def generate(self, request: ValueLogicRequest) -> ValueLogicResult:
        resources = self._load_resource_context(request.site_id, request.project_id)
        local_ctx = self._load_local_context(request.node_path, resources)
        ctx = GenerationContext(
            resources=resources,
            local_ctx=local_ctx,
            node=request.node,
            parent_node=request.parent_node,
            query=request.query,
        )

        if self._is_simple_leaf(request.node):
            return self._generate_simple_leaf_expression(request, ctx)

        if self._is_field(request.node):
            return self._generate_field_logic(request, ctx)

        raise ValueError("Unsupported node type for value logic generation")

    def _load_resource_context(self, site_id: str, project_id: str) -> ResourceContext:
        edsl_tree = self._load_project_edsl_tree()
        return ResourceContext(
            loaded=self.resource_loader.load_resource(
                site_id,
                project_id,
                edsl_tree,
            )
        )

    @staticmethod
    def _load_local_context(node_path: str, resources: ResourceContext) -> list[dict[str, Any]]:
        return [
            local_context.model_dump()
            for local_context in resources.loaded.get_visible_local_context_registry(node_path).values()
        ]

    def _load_project_edsl_tree(self) -> dict[str, Any]:
        tree_path = self.resource_loader.data_dir / "edsl_tree.json"
        if not tree_path.exists():
            return {}
        with tree_path.open("r", encoding="utf-8") as tree_file:
            payload = json.load(tree_file)
        if not isinstance(payload, dict):
            raise ValueError(f"EDSL tree resource must contain a JSON object: {tree_path}")
        return payload

    def _is_simple_leaf(self, node: dict[str, Any]) -> bool:
        return self._node_type(node) == "simple_leaf"

    def _is_field(self, node: dict[str, Any]) -> bool:
        return self._node_type(node) == "field"

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
        diagnostics = list(ctx.diagnostics)
        diagnostics.append("TODO: summary expression generation is not implemented yet.")
        if summary_type is None:
            diagnostics.append("Unable to identify summary_type as sum or count from node metadata.")
        if detail_field is None:
            diagnostics.append("Unable to identify detail_field from node metadata.")

        return ValueLogicResult(
            node_id=self._node_id(request.node),
            logic_type="summary",
            expression=None,
            source=ValueLogicSource(
                source_type="detail_field",
                detail_field=detail_field,
                summary_type=summary_type,
            ),
            diagnostics=diagnostics,
        )

    def _generate_normal_field_logic(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        if request.parent_node and self._is_ab_parent(request.parent_node):
            if self._is_sql_source(request.parent_node):
                mapping_result = self._try_generate_bo_field_mapping(request, ctx)
                if mapping_result is not None:
                    return mapping_result

                return self._generate_expression_by_plan(request, ctx)

            return self._generate_expression_by_plan(request, ctx)

        return self._generate_expression_by_plan(request, ctx)

    def _try_generate_bo_field_mapping(
        self,
        request: ValueLogicRequest,
        ctx: GenerationContext,
    ) -> ValueLogicResult | None:
        # TODO: Add BO property matching inside this branch when the project has
        # a stable source-to-BO mapping contract for AB SQL parents.
        ctx.diagnostics.append("TODO: BO field mapping is not implemented yet; falling back to plan expression generation.")
        return None

    def _generate_expression_by_plan(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        node_info = self._to_node_def(request.node, request.node_path)
        filtered_env = build_filtered_environment(
            node_info=node_info,
            user_query=request.query,
            registry=ctx.resources.loaded,
            llm_resource_filter=self.llm_resource_filter,
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
            source=ValueLogicSource(source_type="plan"),
            diagnostics=list(ctx.diagnostics),
        )

    def _to_node_def(self, node: dict[str, Any], node_path: str) -> NodeDef:
        return NodeDef(
            node_id=self._node_id(node) or "",
            node_path=node_path,
            node_name=self._node_name(node),
            description=str(node.get("description") or node.get("annotation") or ""),
            is_ab=bool(node.get("is_ab")),
            ab_data_source=node.get("ab_data_source") if isinstance(node.get("ab_data_source"), dict) else {},
        )

    def _is_ab_parent(self, parent_node: dict[str, Any]) -> bool:
        return bool(parent_node.get("is_ab"))

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
        return any(self._normalize_text(value) == "sql" for value in source_values)

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
