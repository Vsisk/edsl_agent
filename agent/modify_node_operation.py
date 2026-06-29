from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Literal

from agent.generate_node_operation import (
    GenerateNodeOperation,
    OperationFailure,
    PathResolver,
    TypeSpecificFieldGenerator,
)
from pydantic import BaseModel, Field, ValidationError
from models import DataExpressionTerm, DataTypeTerm, TreeNodeTerm
from agent.models import ValueLogicRequest
from agent.value_logic_generator import ValueLogicGenerator


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

        segments = self.path_resolver._pointer_segments(resolved.normalized_path)
        value: Any = edsl_tree
        ancestor_nodes: list[dict[str, Any]] = []
        for segment in segments:
            value = value[int(segment)] if isinstance(value, list) else value[segment]
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


class ModifyIntentRouter:
    _TYPE_PATTERNS: tuple[tuple[str, ModifyNodeType], ...] = (
        ("普通字段", "simple_leaf"),
        ("叶子节点", "simple_leaf"),
        ("列表节点", "parent_list"),
        ("父节点", "parent"),
        ("透视表", "ab_pivot_table"),
        ("两级表", "ab_two_level_table"),
        ("简单映射表", "ab_single_mapping_table"),
    )
    _CATEGORY_RULES: tuple[tuple[ModifyIntentType, tuple[str, ...], list[str]], ...] = (
        ("modify_ab_content", ("group by", "detail field", "summary field", "透视表字段", "两级表字段"), ["ab_content"]),
        ("modify_context", ("local context", "iter context", "局部变量", "本地上下文"), ["local_context", "iter_local_context"]),
        ("modify_data_source", ("数据源", "循环来源", "namingsql", "naming sql", "BO"), ["data_source"]),
        ("modify_expression", ("取值逻辑", "表达式", "通过 context", "$ctx$", "function", "获取值"), ["data_expression"]),
        ("modify_datatype", ("金额类型", "时间类型", "字符串类型", "精度", "币种", "时间格式"), ["data_type_config"]),
        ("set_common_field", ("xml 名称", "xml_name", "注释", "标签", "logic area"), ["xml_name_property", "annotation", "reference_logic_area_id_list"]),
    )

    def route(self, query: str) -> ModifyIntent:
        lowered = query.lower()
        if any(marker in query for marker in ("改成", "改为", "转换成", "转换为")):
            for term, target in self._TYPE_PATTERNS:
                if term.lower() in lowered:
                    return ModifyIntent(
                        intent_type="change_node_type",
                        target_tree_node_type=target,
                        affected_fields=["tree_node_type"],
                        reason=f"query requests migration to {target}",
                    )

        matches: list[tuple[ModifyIntentType, list[str]]] = []
        for intent_type, terms, fields in self._CATEGORY_RULES:
            if any(term.lower() in lowered for term in terms):
                matches.append((intent_type, fields))
        if not matches:
            raise OperationFailure(
                "MODIFY_INTENT_ROUTE_FAILED",
                "modify intent could not be determined",
            )
        if len(matches) == 1:
            intent_type, fields = matches[0]
            return ModifyIntent(
                intent_type=intent_type,
                affected_fields=fields,
                requires_expression_generation=intent_type == "modify_expression",
                requires_resource_selection=intent_type in {"modify_expression", "modify_data_source"},
                reason=f"query matches {intent_type}",
            )
        return ModifyIntent(
            intent_type="mixed",
            affected_fields=list(dict.fromkeys(field for _, fields in matches for field in fields)),
            requires_expression_generation=any(item[0] == "modify_expression" for item in matches),
            requires_resource_selection=any(item[0] in {"modify_expression", "modify_data_source"} for item in matches),
            reason="query contains multiple modification categories",
        )


class ModifyPlanGenerator:
    _XML_NAME = re.compile(
        r"(?:XML\s*名称|xml_name)\s*(?:改成|改为|为|=|:)\s*([A-Za-z][A-Za-z0-9_]*)",
        re.IGNORECASE,
    )
    _ANNOTATION = re.compile(r"注释\s*(?:改成|改为|为|=|:)\s*([^，,。;；]+)")
    _LOGIC_AREA_ID = re.compile(
        r"logic(?:[\s_-]+area)?[\s_-]*id\s*[:=：]\s*([A-Za-z0-9_-]+)",
        re.IGNORECASE,
    )

    def generate(self, intent: ModifyIntent, query: str) -> NodeModifyPlan:
        common_updates: dict[str, Any] = {}
        xml_updates: dict[str, Any] = {}
        xml_match = self._XML_NAME.search(query)
        if xml_match:
            xml_updates["xml_name"] = xml_match.group(1)
        if "半标签" in query:
            xml_updates["xml_empty_field_type"] = "half"
        elif "全标签" in query:
            xml_updates["xml_empty_field_type"] = "full"
        if "属性输出" in query:
            xml_updates["xml_format_type"] = "property"
        elif "标签输出" in query:
            xml_updates["xml_format_type"] = "label"
        if xml_updates:
            common_updates["xml_name_property"] = xml_updates

        annotation_match = self._ANNOTATION.search(query)
        if annotation_match:
            common_updates["annotation"] = annotation_match.group(1).strip()
        logic_area_ids = list(dict.fromkeys(self._LOGIC_AREA_ID.findall(query)))
        if logic_area_ids:
            common_updates["reference_logic_area_id_list"] = logic_area_ids

        return NodeModifyPlan(
            intent=intent,
            common_field_updates=common_updates,
            expression_update_query=query if intent.intent_type in {"modify_expression", "mixed"} and "data_expression" in intent.affected_fields else None,
            datatype_update_query=query if intent.intent_type in {"modify_datatype", "mixed"} and "data_type_config" in intent.affected_fields else None,
            data_source_update_query=query if intent.intent_type in {"modify_data_source", "mixed"} and "data_source" in intent.affected_fields else None,
            ab_content_update_query=query if intent.intent_type in {"modify_ab_content", "mixed"} and "ab_content" in intent.affected_fields else None,
        )


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

    def __init__(self, type_specific_generator: TypeSpecificFieldGenerator | None = None):
        self.type_specific_generator = type_specific_generator or TypeSpecificFieldGenerator()

    def migrate(
        self,
        original_node: dict[str, Any],
        migration_plan: NodeTypeMigrationPlan,
        query: str,
    ) -> tuple[dict[str, Any], MigrationReport]:
        try:
            target_fields = self.type_specific_generator.generate(
                migration_plan.target_tree_node_type,
                query,
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

        if "重建节点" in query or "rebuild node" in query.lower():
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
            if field == "xml_name_property":
                xml_name_property = dict(candidate.get("xml_name_property") or {})
                xml_name_property.update(deepcopy(value))
                candidate[field] = xml_name_property
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

        if plan.datatype_update_query is not None:
            if candidate.get("tree_node_type") != "simple_leaf":
                raise OperationFailure(
                    "DATATYPE_VALIDATION_FAILED",
                    "data type can only be modified on simple_leaf",
                )
            data_type_payload = dict(candidate.get("data_type_config") or {})
            lowered = plan.datatype_update_query.lower()
            if any(term in lowered for term in ("金额", "money")):
                data_type_payload["data_type"] = "money"
            elif any(term in lowered for term in ("时间", "日期", "time", "date")):
                data_type_payload["data_type"] = "time"
            elif any(term in lowered for term in ("字符串", "string")):
                data_type_payload["data_type"] = "simple_string"
            precision = re.search(r"精度\s*(?:改成|改为|为|=)?\s*(\d+)", plan.datatype_update_query)
            if precision:
                data_type_payload["decimal_precision"] = precision.group(1)
            try:
                candidate["data_type_config"] = DataTypeTerm.model_validate(data_type_payload).model_dump(exclude_none=True)
            except ValidationError as exc:
                raise OperationFailure(
                    "DATATYPE_VALIDATION_FAILED",
                    "data type configuration is invalid",
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
    _AUTHORIZATION_TERMS = ("删除", "清空", "丢弃", "覆盖", "重建", "delete", "clear", "drop", "overwrite", "rebuild")

    def check(
        self,
        *,
        original_node: dict[str, Any],
        candidate_node: dict[str, Any],
        query: str,
        allow_destructive: bool,
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
        explicitly_authorized = any(term.lower() in query.lower() for term in self._AUTHORIZATION_TERMS)
        if not allow_destructive or not explicitly_authorized:
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
        self.intent_router = intent_router or ModifyIntentRouter()
        self.plan_generator = plan_generator or ModifyPlanGenerator()
        self.migration_planner = migration_planner or MigrationPlanner()
        self.executor = executor or ModifyExecutor()
        self.destructive_guard = destructive_guard or DestructiveChangeGuard()
        self.semantic_validator = semantic_validator or SemanticValidator()
        self.patch_builder = patch_builder or ModifyPatchBuilder()
        self.expression_adapter = expression_adapter or ExistingExpressionAdapter()
        self.data_source_adapter = data_source_adapter
        self.ab_content_adapter = ab_content_adapter
        self.intent_llm = intent_llm
        self.plan_llm = plan_llm

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
                    original_node, plan.migration_plan, operation_input.query
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
                query=operation_input.query,
                allow_destructive=operation_input.allow_destructive,
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
        if self.intent_llm is not None:
            try:
                return ModifyIntent.model_validate(self.intent_llm(query, current_node))
            except Exception:
                pass
        try:
            return self.intent_router.route(query)
        except OperationFailure:
            raise
        except Exception as exc:
            raise OperationFailure(
                "MODIFY_INTENT_ROUTE_FAILED",
                "modify intent routing failed",
            ) from exc

    def _generate_plan(
        self,
        intent: ModifyIntent,
        query: str,
        current_node: dict[str, Any],
    ) -> NodeModifyPlan:
        if self.plan_llm is not None:
            try:
                plan = NodeModifyPlan.model_validate(self.plan_llm(query, current_node, intent.model_dump()))
                plan.intent = intent
                return plan
            except Exception:
                pass
        return self.plan_generator.generate(intent, query)
