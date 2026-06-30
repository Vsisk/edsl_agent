from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any, Literal

from agent.generate_node_operation import (
    GenerateNodeOperation,
    NodeContentIntent,
    OperationFailure,
    PathResolver,
    TypeSpecificFieldGenerator,
)
from pydantic import BaseModel, Field, ValidationError
from models import DataExpressionTerm, DataTypeTerm, TreeNodeTerm
from agent.models import ValueLogicRequest
from agent.value_logic_generator import ValueLogicGenerator
from agent.llm.generate_by_llm import generate_by_llm


@dataclass(frozen=True)
class ResolvedTargetNode:
    node_path: str
    node_pointer: str
    current_node: dict[str, Any]
    parent_node: dict[str, Any] | None
    ancestor_nodes: list[dict[str, Any]]
    visible_local_context: list[dict[str, Any]]


class NodeResolver:
    def __init__(self, path_resolver: PathResolver | None = None):
        self.path_resolver = path_resolver or PathResolver()

    def resolve(self, edsl_tree: dict[str, Any], node_path: str) -> ResolvedTargetNode:
        resolved = self.path_resolver.resolve_value(edsl_tree, node_path)
        if not isinstance(resolved.value, dict):
            raise OperationFailure(
                "TARGET_NODE_NOT_FOUND",
                "target path does not resolve to a node object",
                node_path=resolved.normalized_path,
            )

        segments = resolved.tokens
        value: Any = edsl_tree
        ancestor_nodes: list[dict[str, Any]] = []
        for segment in segments:
            value = value[segment]
            if (
                isinstance(value, dict)
                and "tree_node_type" in value
                and value is not resolved.value
            ):
                ancestor_nodes.append(value)

        context_nodes = [*ancestor_nodes, resolved.value]
        visible_context: list[dict[str, Any]] = []
        for node in context_nodes:
            for field_name in ("local_context", "iter_local_context"):
                items = node.get(field_name) or []
                if isinstance(items, list):
                    visible_context.extend(item for item in items if isinstance(item, dict))

        return ResolvedTargetNode(
            node_path=resolved.normalized_path,
            node_pointer=resolved.pointer_path,
            current_node=resolved.value,
            parent_node=ancestor_nodes[-1] if ancestor_nodes else None,
            ancestor_nodes=ancestor_nodes,
            visible_local_context=visible_context,
        )


ModifyIntentType = Literal[
    "set_common_field",
    "modify_expression",
    "modify_datatype",
    "modify_data_source",
    "modify_context",
    "modify_ab_content",
    "change_node_type",
    "mixed",
]
ModifyNodeType = Literal[
    "parent",
    "simple_leaf",
    "parent_list",
    "ab_pivot_table",
    "ab_two_level_table",
    "ab_single_mapping_table",
]


class ModifyIntent(BaseModel):
    intent_type: ModifyIntentType
    target_tree_node_type: ModifyNodeType | None = None
    affected_fields: list[str] = Field(default_factory=list)
    requires_expression_generation: bool = False
    requires_resource_selection: bool = False
    destructive_risk: bool = False
    reason: str = ""


class NodeTypeMigrationPlan(BaseModel):
    source_tree_node_type: str
    target_tree_node_type: ModifyNodeType
    preserve_base_fields: list[str] = Field(
        default_factory=lambda: [
            "node_id",
            "xml_name_property",
            "annotation",
            "edsl_semi_struct",
            "edsl_prompt",
            "reference_logic_area_id_list",
        ]
    )
    preserve_type_fields: list[str] = Field(default_factory=list)
    initialize_fields: list[str] = Field(default_factory=list)
    drop_fields: list[str] = Field(default_factory=list)
    children_policy: Literal[
        "keep", "drop", "move_to_archive", "reject_if_exists", "initialize_empty"
    ] = "initialize_empty"
    local_context_policy: Literal["keep", "drop", "initialize_empty"] = "initialize_empty"
    iter_context_policy: Literal["keep", "drop", "initialize_empty"] = "initialize_empty"
    destructive_risk: bool = False
    reason: str = ""


class NodeModifyPlan(BaseModel):
    intent: ModifyIntent
    common_field_updates: dict[str, Any] = Field(default_factory=dict)
    type_field_updates: dict[str, Any] = Field(default_factory=dict)
    expression_update_query: str | None = None
    datatype_update_query: str | None = None
    data_source_update_query: str | None = None
    ab_content_update_query: str | None = None
    migration_plan: NodeTypeMigrationPlan | None = None
    destructive_authorized: bool = False
    rebuild_node: bool = False


class ModifyIntentRouter:
    def __init__(self, llm_gateway: Any | None = None):
        self.llm_gateway = llm_gateway

    def route(self, query: str, current_node: dict[str, Any] | None = None) -> ModifyIntent:
        current_node = current_node or {}
        try:
            payload = (
                self.llm_gateway(query, current_node)
                if self.llm_gateway is not None
                else generate_by_llm(
                    "modify_intent_route_prompt",
                    query=query,
                    current_node_json=json.dumps(current_node, ensure_ascii=False),
                )
            )
            return ModifyIntent.model_validate(payload)
        except Exception as exc:
            raise OperationFailure(
                "MODIFY_INTENT_ROUTE_FAILED",
                "LLM modify intent routing failed",
            ) from exc


class ModifyPlanGenerator:
    def __init__(self, llm_gateway: Any | None = None):
        self.llm_gateway = llm_gateway

    def generate(
        self,
        intent: ModifyIntent,
        query: str,
        current_node: dict[str, Any] | None = None,
    ) -> NodeModifyPlan:
        current_node = current_node or {}
        try:
            payload = (
                self.llm_gateway(query, current_node, intent.model_dump())
                if self.llm_gateway is not None
                else generate_by_llm(
                    "modify_plan_prompt",
                    query=query,
                    current_node_json=json.dumps(current_node, ensure_ascii=False),
                    modify_intent_json=intent.model_dump_json(),
                )
            )
            plan = NodeModifyPlan.model_validate(payload)
            plan.intent = intent
            return plan
        except Exception as exc:
            raise OperationFailure(
                "MODIFY_PLAN_GENERATION_FAILED",
                "LLM modify plan generation failed",
            ) from exc


class MigrationReport(BaseModel):
    source_tree_node_type: str
    target_tree_node_type: str
    preserved_fields: list[str] = Field(default_factory=list)
    initialized_fields: list[str] = Field(default_factory=list)
    dropped_fields: list[str] = Field(default_factory=list)
    children_action: Literal["keep", "drop", "initialize_empty", "none"] = "none"
    original_children_count: int = 0
    destructive_risk: bool = False


class MigrationPlanner:
    _OPTIONAL_FIELDS = {
        "data_expression",
        "data_type_config",
        "children",
        "ab_content",
        "local_context",
        "iter_local_context",
        "data_source",
        "support_big_cust_acct",
    }

    def plan(self, current_node: dict[str, Any], target_tree_node_type: ModifyNodeType) -> NodeTypeMigrationPlan:
        source_type = str(current_node.get("tree_node_type") or "")
        if source_type not in TreeNodeTerm.Config.allowed_fields_per_type:
            raise OperationFailure(
                "UNSUPPORTED_TYPE_MIGRATION",
                "source node type is unsupported",
                source_tree_node_type=source_type,
            )
        if target_tree_node_type not in TreeNodeTerm.Config.allowed_fields_per_type:
            raise OperationFailure(
                "UNSUPPORTED_TYPE_MIGRATION",
                "target node type is unsupported",
                target_tree_node_type=target_tree_node_type,
            )

        target_fields = TreeNodeTerm.Config.allowed_fields_per_type[target_tree_node_type]
        drop_fields = sorted(
            field for field in self._OPTIONAL_FIELDS if field in current_node and field not in target_fields
        )
        preserve_type_fields: list[str] = []
        if source_type in {"parent", "parent_list"} and target_tree_node_type in {"parent", "parent_list"}:
            preserve_type_fields = ["children", "local_context"]
        elif source_type.startswith("ab_") and target_tree_node_type.startswith("ab_"):
            preserve_type_fields = ["ab_content.data_source", "ab_content.group_by_fields"]

        destructive_risk = (
            (source_type == "parent_list" and target_tree_node_type == "parent")
            or (source_type in {"parent", "parent_list"} and target_tree_node_type == "simple_leaf")
            or (source_type.startswith("ab_") and not target_tree_node_type.startswith("ab_"))
        )
        children_policy: str = "initialize_empty"
        if "children" in preserve_type_fields:
            children_policy = "keep"
        elif "children" in drop_fields:
            children_policy = "drop"

        return NodeTypeMigrationPlan(
            source_tree_node_type=source_type,
            target_tree_node_type=target_tree_node_type,
            preserve_type_fields=preserve_type_fields,
            initialize_fields=sorted(target_fields - set(preserve_type_fields)),
            drop_fields=drop_fields,
            children_policy=children_policy,
            local_context_policy="keep" if "local_context" in preserve_type_fields else "initialize_empty",
            iter_context_policy="initialize_empty" if target_tree_node_type == "parent_list" else "drop",
            destructive_risk=destructive_risk,
            reason=f"migrate {source_type} to {target_tree_node_type}",
        )


class ModifyExecutor:
    _BASE_FIELDS = {
        "node_id",
        "xml_name_property",
        "annotation",
        "edsl_semi_struct",
        "edsl_prompt",
        "reference_logic_area_id_list",
    }
    _COMMON_UPDATE_FIELDS = {
        "xml_name_property",
        "annotation",
        "reference_logic_area_id_list",
    }

    def __init__(self, type_specific_generator: TypeSpecificFieldGenerator | None = None):
        self.type_specific_generator = type_specific_generator or TypeSpecificFieldGenerator()

    def migrate(
        self,
        original_node: dict[str, Any],
        migration_plan: NodeTypeMigrationPlan,
        query: str,
        *,
        rebuild_node: bool = False,
    ) -> tuple[dict[str, Any], MigrationReport]:
        try:
            target_fields = self.type_specific_generator.generate(
                migration_plan.target_tree_node_type,
                NodeContentIntent(tree_node_type=migration_plan.target_tree_node_type),
            )
        except OperationFailure as exc:
            raise OperationFailure(
                "UNSUPPORTED_TYPE_MIGRATION",
                "target node type cannot be initialized",
                target_tree_node_type=migration_plan.target_tree_node_type,
            ) from exc

        candidate = {
            field: deepcopy(value)
            for field, value in original_node.items()
            if field in self._BASE_FIELDS
        }
        candidate["tree_node_type"] = migration_plan.target_tree_node_type
        candidate.update(deepcopy(target_fields))

        for field in ("children", "local_context"):
            if field in migration_plan.preserve_type_fields:
                candidate[field] = deepcopy(original_node.get(field) or [])

        source_ab = original_node.get("ab_content")
        target_ab = candidate.get("ab_content")
        if isinstance(source_ab, dict) and target_ab is not None:
            target_payload = target_ab.model_dump() if isinstance(target_ab, BaseModel) else dict(target_ab)
            for field in ("data_source", "group_by_fields"):
                if field in source_ab and field in target_payload:
                    target_payload[field] = deepcopy(source_ab[field])
            candidate["ab_content"] = target_payload

        if rebuild_node:
            rebuilt_node = TreeNodeTerm.model_validate(candidate)
            rebuilt_node.update_id()
            candidate["node_id"] = rebuilt_node.node_id

        children = original_node.get("children") or []
        report = MigrationReport(
            source_tree_node_type=migration_plan.source_tree_node_type,
            target_tree_node_type=migration_plan.target_tree_node_type,
            preserved_fields=[
                field for field in migration_plan.preserve_base_fields if field in original_node
            ] + migration_plan.preserve_type_fields,
            initialized_fields=migration_plan.initialize_fields,
            dropped_fields=migration_plan.drop_fields,
            children_action=(
                "keep"
                if migration_plan.children_policy == "keep"
                else "drop"
                if migration_plan.children_policy == "drop"
                else "initialize_empty"
                if "children" in candidate
                else "none"
            ),
            original_children_count=len(children) if isinstance(children, list) else 0,
            destructive_risk=migration_plan.destructive_risk,
        )
        return candidate, report

    def apply_plan(
        self,
        original_node: dict[str, Any],
        plan: NodeModifyPlan,
        context: "ModifyAdapterContext",
        *,
        expression_adapter: Any | None = None,
        data_source_adapter: Any | None = None,
        ab_content_adapter: Any | None = None,
    ) -> dict[str, Any]:
        candidate = deepcopy(original_node)
        for field, value in plan.common_field_updates.items():
            if field not in self._COMMON_UPDATE_FIELDS:
                raise OperationFailure(
                    "UNSUPPORTED_FIELD_UPDATE",
                    "field is not allowed in common_field_updates",
                    field=field,
                )
            if field == "xml_name_property":
                xml_name_property = dict(candidate.get("xml_name_property") or {})
                xml_name_property.update(deepcopy(value))
                candidate[field] = xml_name_property
            else:
                candidate[field] = deepcopy(value)

        for field, value in plan.type_field_updates.items():
            allowed_fields = TreeNodeTerm.Config.allowed_fields_per_type.get(
                str(candidate.get("tree_node_type") or ""),
                set(),
            )
            if field not in allowed_fields:
                raise OperationFailure(
                    "UNSUPPORTED_FIELD_UPDATE",
                    "type field is not allowed for the current node type",
                    field=field,
                )
            if field == "data_type_config":
                try:
                    candidate[field] = DataTypeTerm.model_validate(value).model_dump(exclude_none=True)
                except ValidationError as exc:
                    raise OperationFailure(
                        "DATATYPE_VALIDATION_FAILED",
                        "data type configuration is invalid",
                    ) from exc
            else:
                candidate[field] = deepcopy(value)

        if plan.expression_update_query is not None:
            if candidate.get("tree_node_type") != "simple_leaf":
                raise OperationFailure(
                    "UNSUPPORTED_FIELD_UPDATE",
                    "data_expression can only be modified on simple_leaf",
                )
            if expression_adapter is None:
                raise OperationFailure(
                    "EXPRESSION_GENERATION_FAILED",
                    "expression adapter is not available",
                )
            try:
                expression = expression_adapter(context)
                candidate["data_expression"] = DataExpressionTerm.model_validate(expression).model_dump()
            except OperationFailure:
                raise
            except Exception as exc:
                raise OperationFailure(
                    "EXPRESSION_GENERATION_FAILED",
                    "expression generation failed",
                ) from exc

        if plan.data_source_update_query is not None:
            if data_source_adapter is None:
                raise OperationFailure(
                    "UNSUPPORTED_FIELD_UPDATE",
                    "complex data_source modification requires an adapter",
                )
            try:
                candidate["data_source"] = data_source_adapter(context)
            except Exception as exc:
                raise OperationFailure(
                    "DATA_SOURCE_VALIDATION_FAILED",
                    "data source modification failed",
                ) from exc

        if plan.ab_content_update_query is not None:
            if ab_content_adapter is None:
                raise OperationFailure(
                    "UNSUPPORTED_FIELD_UPDATE",
                    "complex ab_content modification requires an adapter",
                )
            try:
                candidate["ab_content"] = ab_content_adapter(context)
            except Exception as exc:
                raise OperationFailure(
                    "AB_CONTENT_VALIDATION_FAILED",
                    "AB content modification failed",
                ) from exc

        if plan.intent.intent_type == "modify_context":
            raise OperationFailure(
                "UNSUPPORTED_FIELD_UPDATE",
                "context modification requires an explicit context adapter",
            )
        return candidate


class ModifyAdapterContext(BaseModel):
    query: str
    node_path: str = ""
    current_node: dict[str, Any]
    parent_node: dict[str, Any] | None = None
    ancestor_nodes: list[dict[str, Any]] = Field(default_factory=list)
    visible_local_context: list[dict[str, Any]] = Field(default_factory=list)
    edsl_tree: dict[str, Any]
    site_id: str | None = None
    project_id: str | None = None


class ExistingExpressionAdapter:
    def __init__(self, generator: ValueLogicGenerator | None = None):
        self.generator = generator or ValueLogicGenerator()

    def __call__(self, context: ModifyAdapterContext) -> DataExpressionTerm:
        if not context.site_id or not context.project_id:
            raise ValueError("site_id and project_id are required for expression generation")
        result = self.generator.generate(
            ValueLogicRequest(
                site_id=context.site_id,
                project_id=context.project_id,
                node_path=context.node_path,
                node=context.current_node,
                parent_node=context.parent_node,
                query=context.query,
                is_ab=str(context.current_node.get("tree_node_type") or "").startswith("ab_"),
                edsl_tree=context.edsl_tree,
            )
        )
        if result.logic_type != "expression" or result.expression is None:
            raise ValueError("existing value-logic generator did not return an expression")
        return DataExpressionTerm(expression=result.expression)


class DestructiveChangeGuard:
    def check(
        self,
        *,
        original_node: dict[str, Any],
        candidate_node: dict[str, Any],
        allow_destructive: bool,
        destructive_authorized: bool,
        migration_report: MigrationReport | None,
    ) -> MigrationReport | None:
        report = migration_report
        same_node_type = original_node.get("tree_node_type") == candidate_node.get("tree_node_type")
        expression_overwrite = bool(
            same_node_type
            and
            (original_node.get("data_expression") or {}).get("expression")
            and original_node.get("data_expression") != candidate_node.get("data_expression")
        )
        data_source_overwrite = bool(
            same_node_type
            and
            original_node.get("data_source")
            and original_node.get("data_source") != candidate_node.get("data_source")
        )
        destructive = bool(report and report.destructive_risk) or expression_overwrite or data_source_overwrite
        if not destructive:
            return report
        if report is None:
            node_type = str(original_node.get("tree_node_type") or "")
            report = MigrationReport(
                source_tree_node_type=node_type,
                target_tree_node_type=str(candidate_node.get("tree_node_type") or node_type),
                destructive_risk=True,
            )
        else:
            report.destructive_risk = True
        if not allow_destructive or not destructive_authorized:
            raise OperationFailure(
                "DESTRUCTIVE_CHANGE_NOT_ALLOWED",
                "destructive modification requires allow_destructive and explicit query authorization",
            )
        return report


class SemanticValidator:
    def validate(self, node: TreeNodeTerm) -> None:
        if node.tree_node_type == "simple_leaf" and node.data_expression is None:
            raise OperationFailure("EXPRESSION_GENERATION_FAILED", "simple_leaf requires data_expression")
        if node.tree_node_type == "parent_list" and node.data_source is None:
            raise OperationFailure("DATA_SOURCE_VALIDATION_FAILED", "parent_list requires data_source")
        if node.tree_node_type.startswith("ab_"):
            if node.ab_content is None:
                raise OperationFailure("AB_CONTENT_VALIDATION_FAILED", "AB node requires ab_content")
            if node.ab_content.tree_node_type != node.tree_node_type:
                raise OperationFailure("AB_CONTENT_VALIDATION_FAILED", "AB inner and outer types differ")


class ModifyNodeOperationInput(BaseModel):
    query: str
    node_path: str
    edsl_tree: dict[str, Any]
    site_id: str | None = None
    project_id: str | None = None
    debug: bool = False
    allow_destructive: bool = False


class ModifyNodeOperationOutput(BaseModel):
    success: bool
    operation_type: Literal["modify_node"] = "modify_node"
    node_path: str
    original_node: dict[str, Any] | None = None
    modified_node: dict[str, Any] | None = None
    patch_list: list[dict[str, Any]] = Field(default_factory=list)
    modify_intent: dict[str, Any] | None = None
    migration_report: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    failure_reason: str | None = None


class ModifyPatchBuilder:
    def build(self, node_pointer: str, modified_node: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"op": "replace", "path": node_pointer, "value": modified_node}]


class ModifyNodeOperation:
    def __init__(
        self,
        *,
        node_resolver: NodeResolver | None = None,
        intent_router: ModifyIntentRouter | None = None,
        plan_generator: ModifyPlanGenerator | None = None,
        migration_planner: MigrationPlanner | None = None,
        executor: ModifyExecutor | None = None,
        destructive_guard: DestructiveChangeGuard | None = None,
        semantic_validator: SemanticValidator | None = None,
        patch_builder: ModifyPatchBuilder | None = None,
        expression_adapter: Any | None = None,
        data_source_adapter: Any | None = None,
        ab_content_adapter: Any | None = None,
        intent_llm: Any | None = None,
        plan_llm: Any | None = None,
    ):
        self.node_resolver = node_resolver or NodeResolver()
        self.intent_router = intent_router or ModifyIntentRouter(intent_llm)
        self.plan_generator = plan_generator or ModifyPlanGenerator(plan_llm)
        self.migration_planner = migration_planner or MigrationPlanner()
        self.executor = executor or ModifyExecutor()
        self.destructive_guard = destructive_guard or DestructiveChangeGuard()
        self.semantic_validator = semantic_validator or SemanticValidator()
        self.patch_builder = patch_builder or ModifyPatchBuilder()
        self.expression_adapter = expression_adapter or ExistingExpressionAdapter()
        self.data_source_adapter = data_source_adapter
        self.ab_content_adapter = ab_content_adapter

    def execute(self, operation_input: ModifyNodeOperationInput) -> ModifyNodeOperationOutput:
        resolved: ResolvedTargetNode | None = None
        intent: ModifyIntent | None = None
        original_node: dict[str, Any] | None = None
        try:
            resolved = self.node_resolver.resolve(operation_input.edsl_tree, operation_input.node_path)
            original_node = deepcopy(resolved.current_node)
            intent = self._route_intent(operation_input.query, original_node)
            plan = self._generate_plan(intent, operation_input.query, original_node)
            context = ModifyAdapterContext(
                query=operation_input.query,
                node_path=resolved.node_path,
                current_node=original_node,
                parent_node=deepcopy(resolved.parent_node),
                ancestor_nodes=deepcopy(resolved.ancestor_nodes),
                visible_local_context=deepcopy(resolved.visible_local_context),
                edsl_tree=operation_input.edsl_tree,
                site_id=operation_input.site_id,
                project_id=operation_input.project_id,
            )

            migration_report: MigrationReport | None = None
            if intent.intent_type == "change_node_type":
                if intent.target_tree_node_type is None:
                    raise OperationFailure("UNSUPPORTED_TYPE_MIGRATION", "target type is missing")
                plan.migration_plan = self.migration_planner.plan(original_node, intent.target_tree_node_type)
                candidate, migration_report = self.executor.migrate(
                    original_node,
                    plan.migration_plan,
                    operation_input.query,
                    rebuild_node=plan.rebuild_node,
                )
            else:
                candidate = self.executor.apply_plan(
                    original_node,
                    plan,
                    context,
                    expression_adapter=self.expression_adapter,
                    data_source_adapter=self.data_source_adapter,
                    ab_content_adapter=self.ab_content_adapter,
                )

            migration_report = self.destructive_guard.check(
                original_node=original_node,
                candidate_node=candidate,
                allow_destructive=operation_input.allow_destructive,
                destructive_authorized=plan.destructive_authorized,
                migration_report=migration_report,
            )
            validated = TreeNodeTerm.model_validate(candidate)
            self.semantic_validator.validate(validated)
            modified_node = GenerateNodeOperation._serialize_node(validated)
            return ModifyNodeOperationOutput(
                success=True,
                node_path=operation_input.node_path,
                original_node=original_node,
                modified_node=modified_node,
                patch_list=self.patch_builder.build(resolved.node_pointer, modified_node),
                modify_intent=intent.model_dump(),
                migration_report=migration_report.model_dump() if migration_report else None,
            )
        except OperationFailure as exc:
            return self._failure(operation_input, original_node, intent, exc.code, [exc.to_detail()])
        except ValidationError as exc:
            return self._failure(
                operation_input,
                original_node,
                intent,
                "NODE_SCHEMA_VALIDATION_FAILED",
                [{"code": "NODE_SCHEMA_VALIDATION_FAILED", "message": item["msg"], "context": {"location": list(item["loc"]), "type": item["type"]}} for item in exc.errors(include_url=False)],
            )

    @staticmethod
    def _failure(
        operation_input: ModifyNodeOperationInput,
        original_node: dict[str, Any] | None,
        intent: ModifyIntent | None,
        reason: str,
        errors: list[dict[str, Any]],
    ) -> ModifyNodeOperationOutput:
        return ModifyNodeOperationOutput(
            success=False,
            node_path=operation_input.node_path,
            original_node=original_node,
            modify_intent=intent.model_dump() if intent else None,
            validation_errors=errors,
            failure_reason=reason,
        )

    def _route_intent(self, query: str, current_node: dict[str, Any]) -> ModifyIntent:
        return self.intent_router.route(query, current_node)

    def _generate_plan(
        self,
        intent: ModifyIntent,
        query: str,
        current_node: dict[str, Any],
    ) -> NodeModifyPlan:
        return self.plan_generator.generate(intent, query, current_node)
