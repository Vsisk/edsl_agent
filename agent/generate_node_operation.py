from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal

from jsonpath_ng import parse
from pydantic import BaseModel, Field, ValidationError
from agent.llm.generate_by_llm import generate_by_llm

from models import (
    DataExpressionTerm,
    DataSourceTerm,
    DataTypeTerm,
    PivotTableTerm,
    SupportBigCustAcctTerm,
    TwoLevelTableTerm,
    TreeNodeTerm,
    XmlNamePropertyTerm,
)


NodeType = Literal[
    "simple_leaf",
    "parent",
    "parent_list",
    "ab_pivot_table",
    "ab_two_level_table",
]


class GenerateNodeOperationInput(BaseModel):
    query: str
    node_path: str
    edsl_tree: dict[str, Any]
    debug: bool = False


class GenerateNodeOperationOutput(BaseModel):
    success: bool
    operation_type: Literal["generate_node"] = "generate_node"
    node_path: str
    parent_path: str | None = None
    children_path: str | None = None
    generated_node: dict[str, Any] | None = None
    patch: dict[str, Any] | None = None
    route_result: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    failure_reason: str | None = None


class OperationFailure(Exception):
    def __init__(self, code: str, message: str, **context: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.context:
            detail["context"] = self.context
        return detail


@dataclass(frozen=True)
class ResolvedNodePath:
    parent_path: str
    children_path: str
    patch_path: str
    parent_node: dict[str, Any]


@dataclass(frozen=True)
class ResolvedValuePath:
    normalized_path: str
    pointer_path: str
    value: Any


class PathResolver:
    _SUPPORTED_PATH = re.compile(
        r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])+$"
    )
    _SEGMENT = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]+)\]")
    _CONTAINER_TYPES = {"parent", "parent_list"}

    def resolve(self, edsl_tree: dict[str, Any], node_path: str) -> ResolvedNodePath:
        resolved_value = self.resolve_value(
            edsl_tree,
            node_path,
            missing_error_code="TARGET_PARENT_NOT_FOUND",
        )
        normalized_path = resolved_value.normalized_path
        parent_node = resolved_value.value

        if not isinstance(parent_node, dict):
            raise OperationFailure(
                "TARGET_PARENT_CANNOT_HAVE_CHILDREN",
                "target parent is not a node object",
                node_path=normalized_path,
            )
        if parent_node.get("tree_node_type") not in self._CONTAINER_TYPES:
            raise OperationFailure(
                "TARGET_PARENT_CANNOT_HAVE_CHILDREN",
                "target node type cannot contain children",
                node_path=normalized_path,
                tree_node_type=parent_node.get("tree_node_type"),
            )

        children_path = f"{normalized_path}.children"
        patch_path = f"{resolved_value.pointer_path}/children/-"
        return ResolvedNodePath(
            parent_path=normalized_path,
            children_path=children_path,
            patch_path=patch_path,
            parent_node=parent_node,
        )

    def resolve_value(
        self,
        edsl_tree: dict[str, Any],
        node_path: str,
        *,
        missing_error_code: str = "TARGET_NODE_NOT_FOUND",
    ) -> ResolvedValuePath:
        normalized_path = self._normalize(node_path)
        if not self._SUPPORTED_PATH.fullmatch(normalized_path):
            raise OperationFailure(
                "INVALID_NODE_PATH",
                "node_path must use simple JSONPath property and numeric index segments",
                node_path=node_path,
            )

        try:
            matches = parse(normalized_path).find(edsl_tree)
        except Exception as exc:
            raise OperationFailure(
                "INVALID_NODE_PATH",
                "node_path could not be parsed",
                node_path=node_path,
            ) from exc

        if not matches:
            raise OperationFailure(
                missing_error_code,
                "target node does not exist",
                node_path=normalized_path,
            )
        if len(matches) != 1:
            raise OperationFailure(
                "INVALID_NODE_PATH",
                "node_path must resolve to exactly one parent",
                node_path=normalized_path,
            )

        pointer_segments = self._pointer_segments(normalized_path)
        return ResolvedValuePath(
            normalized_path=normalized_path,
            pointer_path="/" + "/".join(pointer_segments),
            value=matches[0].value,
        )

    @staticmethod
    def _normalize(node_path: str) -> str:
        path = node_path.strip()
        if path and not path.startswith("$"):
            path = f"$.{path.lstrip('.')}"
        return path

    def _pointer_segments(self, node_path: str) -> list[str]:
        segments: list[str] = []
        for match in self._SEGMENT.finditer(node_path):
            segment = match.group(1) or match.group(2)
            segments.append(segment.replace("~", "~0").replace("/", "~1"))
        return segments


class NodeRouteResult(BaseModel):
    tree_node_type: NodeType
    confidence: float = 1.0
    reason: str
    evidence_terms: list[str] = Field(default_factory=list)
    source: Literal["local", "llm"] = "local"


class CommonNodeFields(BaseModel):
    xml_name_property: XmlNamePropertyTerm
    annotation: str = ""
    reference_logic_area_id_list: list[str] = Field(default_factory=list)


class NodeTypeRouter:
    def __init__(self, llm_gateway: Any | None = None):
        self.llm_gateway = llm_gateway

    def route(self, query: str) -> NodeRouteResult:
        try:
            payload = (
                self.llm_gateway(query)
                if self.llm_gateway is not None
                else generate_by_llm("node_type_route_prompt", query=query)
            )
            result = NodeRouteResult.model_validate(payload)
            result.source = "llm"
            return result
        except Exception as exc:
            raise OperationFailure("NODE_TYPE_ROUTE_FAILED", "LLM node type routing failed") from exc


class CommonFieldGenerator:
    def __init__(self, llm_gateway: Any | None = None):
        self.llm_gateway = llm_gateway

    def generate(self, query: str) -> CommonNodeFields:
        try:
            payload = (
                self.llm_gateway(query)
                if self.llm_gateway is not None
                else generate_by_llm("common_node_field_prompt", query=query)
            )
            result = CommonNodeFields.model_validate(payload)
            if not result.xml_name_property.xml_name or not result.xml_name_property.xml_name.strip():
                raise ValueError("xml_name is empty")
            return result
        except Exception as exc:
            raise OperationFailure(
                "COMMON_FIELD_GENERATION_FAILED",
                "LLM common field generation failed",
            ) from exc


class NodeContentIntent(BaseModel):
    tree_node_type: NodeType
    data_type: Literal["simple_string", "time", "money"] = "simple_string"
    requires_expression_generation: bool = False
    requires_data_source_generation: bool = False
    expression_query: str | None = None
    data_source_query: str | None = None
    ab_content_query: str | None = None
    reason: str = ""


class NodeContentIntentGenerator:
    def __init__(self, llm_gateway: Any | None = None):
        self.llm_gateway = llm_gateway

    def generate(self, query: str, tree_node_type: NodeType) -> NodeContentIntent:
        try:
            payload = (
                self.llm_gateway(query, tree_node_type)
                if self.llm_gateway is not None
                else generate_by_llm(
                    "node_content_intent_prompt",
                    query=query,
                    tree_node_type=tree_node_type,
                )
            )
            result = NodeContentIntent.model_validate(payload)
            if result.tree_node_type != tree_node_type:
                raise ValueError("content intent node type differs from route")
            return result
        except Exception as exc:
            raise OperationFailure(
                "NODE_CONTENT_INTENT_FAILED",
                "LLM node content intent generation failed",
            ) from exc


class TypeSpecificFieldGenerator:
    def generate(self, tree_node_type: NodeType, intent: NodeContentIntent) -> dict[str, Any]:
        if tree_node_type == "simple_leaf":
            return {
                "data_expression": DataExpressionTerm(),
                "data_type_config": DataTypeTerm(data_type=intent.data_type),
                "support_big_cust_acct": SupportBigCustAcctTerm(),
            }
        if tree_node_type == "parent":
            return {"children": [], "local_context": []}
        if tree_node_type == "parent_list":
            return {
                "data_source": DataSourceTerm(),
                "support_big_cust_acct": SupportBigCustAcctTerm(),
                "children": [],
                "local_context": [],
                "iter_local_context": [],
            }
        if tree_node_type == "ab_pivot_table":
            return {"ab_content": PivotTableTerm()}
        if tree_node_type == "ab_two_level_table":
            return {"ab_content": TwoLevelTableTerm()}
        raise OperationFailure(
            "TYPE_SPECIFIC_FIELD_MISSING",
            "unsupported node type has no type-specific field generator",
            tree_node_type=tree_node_type,
        )


class NodeAssembler:
    _REQUIRED_FIELDS: dict[NodeType, set[str]] = {
        "simple_leaf": {"data_expression", "data_type_config", "support_big_cust_acct"},
        "parent": {"children", "local_context"},
        "parent_list": {
            "data_source",
            "support_big_cust_acct",
            "children",
            "local_context",
            "iter_local_context",
        },
        "ab_pivot_table": {"ab_content"},
        "ab_two_level_table": {"ab_content"},
    }

    def assemble(
        self,
        route: NodeRouteResult,
        common_fields: CommonNodeFields,
        type_specific_fields: dict[str, Any],
    ) -> dict[str, Any]:
        required = self._REQUIRED_FIELDS[route.tree_node_type]
        missing = sorted(required - type_specific_fields.keys())
        if missing:
            raise OperationFailure(
                "TYPE_SPECIFIC_FIELD_MISSING",
                "required type-specific fields are missing",
                tree_node_type=route.tree_node_type,
                missing_fields=missing,
            )
        return {
            "tree_node_type": route.tree_node_type,
            **common_fields.model_dump(),
            **type_specific_fields,
        }


class NodePatchBuilder:
    def build(self, patch_path: str, generated_node: dict[str, Any]) -> dict[str, Any]:
        return {"op": "add", "path": patch_path, "value": generated_node}


class GenerateNodeOperation:
    def __init__(
        self,
        *,
        path_resolver: PathResolver | None = None,
        node_type_router: NodeTypeRouter | None = None,
        common_field_generator: CommonFieldGenerator | None = None,
        type_specific_field_generator: TypeSpecificFieldGenerator | None = None,
        node_assembler: NodeAssembler | None = None,
        patch_builder: NodePatchBuilder | None = None,
        route_llm: Any | None = None,
        common_fields_llm: Any | None = None,
        content_intent_llm: Any | None = None,
        content_intent_generator: NodeContentIntentGenerator | None = None,
    ):
        self.path_resolver = path_resolver or PathResolver()
        self.node_type_router = node_type_router or NodeTypeRouter(route_llm)
        self.common_field_generator = common_field_generator or CommonFieldGenerator(common_fields_llm)
        self.content_intent_generator = content_intent_generator or NodeContentIntentGenerator(content_intent_llm)
        self.type_specific_field_generator = (
            type_specific_field_generator or TypeSpecificFieldGenerator()
        )
        self.node_assembler = node_assembler or NodeAssembler()
        self.patch_builder = patch_builder or NodePatchBuilder()

    def execute(self, operation_input: GenerateNodeOperationInput) -> GenerateNodeOperationOutput:
        resolved: ResolvedNodePath | None = None
        route: NodeRouteResult | None = None
        try:
            resolved = self.path_resolver.resolve(
                operation_input.edsl_tree,
                operation_input.node_path,
            )
            route = self._route(operation_input.query)
            common_fields = self._common_fields(operation_input.query)
            content_intent = self.content_intent_generator.generate(
                operation_input.query,
                route.tree_node_type,
            )
            type_specific_fields = self.type_specific_field_generator.generate(
                route.tree_node_type,
                content_intent,
            )
            draft = self.node_assembler.assemble(route, common_fields, type_specific_fields)
            validated_node = TreeNodeTerm.model_validate(draft)
            generated_node = self._serialize_node(validated_node)
            patch = self.patch_builder.build(resolved.patch_path, generated_node)
            return GenerateNodeOperationOutput(
                success=True,
                node_path=operation_input.node_path,
                parent_path=resolved.parent_path,
                children_path=resolved.children_path,
                generated_node=generated_node,
                patch=patch,
                route_result=route.model_dump(),
            )
        except OperationFailure as exc:
            return self._failure_output(operation_input, resolved, route, exc.code, [exc.to_detail()])
        except ValidationError as exc:
            return self._failure_output(
                operation_input,
                resolved,
                route,
                "NODE_SCHEMA_VALIDATION_FAILED",
                [
                    {
                        "code": "NODE_SCHEMA_VALIDATION_FAILED",
                        "message": error["msg"],
                        "context": {
                            "location": list(error["loc"]),
                            "type": error["type"],
                        },
                    }
                    for error in exc.errors(include_url=False)
                ],
            )

    def _route(self, query: str) -> NodeRouteResult:
        try:
            return self.node_type_router.route(query)
        except OperationFailure:
            raise
        except Exception as exc:
            raise OperationFailure("NODE_TYPE_ROUTE_FAILED", "LLM node type routing failed") from exc

    def _common_fields(self, query: str) -> CommonNodeFields:
        try:
            return self.common_field_generator.generate(query)
        except OperationFailure:
            raise
        except Exception as exc:
            raise OperationFailure(
                "COMMON_FIELD_GENERATION_FAILED",
                "LLM common field generation failed",
            ) from exc

    @staticmethod
    def _serialize_node(node: TreeNodeTerm) -> dict[str, Any]:
        payload = node.model_dump(mode="json", exclude_none=True)
        if node.tree_node_type in TreeNodeTerm.Config.ab_table_type_list:
            payload["ab_content"]["tree_node_type"] = node.tree_node_type
        return payload

    @staticmethod
    def _failure_output(
        operation_input: GenerateNodeOperationInput,
        resolved: ResolvedNodePath | None,
        route: NodeRouteResult | None,
        failure_reason: str,
        validation_errors: list[dict[str, Any]],
    ) -> GenerateNodeOperationOutput:
        return GenerateNodeOperationOutput(
            success=False,
            node_path=operation_input.node_path,
            parent_path=resolved.parent_path if resolved else None,
            children_path=resolved.children_path if resolved else None,
            route_result=route.model_dump() if route else None,
            validation_errors=validation_errors,
            failure_reason=failure_reason,
        )
