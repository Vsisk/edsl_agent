from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field



class ASTNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str



class ContextPathNode(ASTNode):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"type": "context_path", "path": "$ctx$.id"}]})

    type: Literal["context_path"]
    path: str


class LiteralNode(ASTNode):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"type": "literal", "value": "abc"}]})

    type: Literal["literal"]
    value: Any


class VariableRefNode(ASTNode):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"type": "variable_ref", "name": "oid"}]})

    type: Literal["variable_ref"]
    name: str


class FieldAccessNode(ASTNode):
    type: Literal["field_access"]
    receiver: ExprNode
    field: str


class MethodCallNode(ASTNode):
    type: Literal["method_call"]
    receiver: ExprNode
    name: str
    args: list[ExprNode] = Field(default_factory=list)
    lambda_expr: ExprNode | None = None


class DefNode(ASTNode):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"type": "def", "name": "oid", "value": {"type": "literal", "value": 1}}]},
    )

    type: Literal["def"]
    name: str
    value: ExprNode
    render_style: Literal["legacy", "simple"] = "legacy"


class CompareNode(ASTNode):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "type": "compare",
                    "op": "==",
                    "left": {"type": "context_path", "path": "it.ID"},
                    "right": {"type": "literal", "value": 1},
                }
            ]
        },
    )

    type: Literal["compare"]
    op: Literal["==", "!=", ">", ">=", "<", "<="]
    left: ExprNode
    right: ExprNode


class LogicalNode(ASTNode):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "type": "logical",
                    "op": "and",
                    "items": [
                        {"type": "literal", "value": True},
                        {"type": "literal", "value": False},
                    ],
                }
            ]
        },
    )

    type: Literal["logical"]
    op: Literal["and", "or"]
    items: list[ExprNode] = Field(min_length=2)


class CallNode(ASTNode):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "type": "call",
                    "name": "IF",
                    "args": [
                        {
                            "type": "compare",
                            "op": "==",
                            "left": {"type": "context_path", "path": "$ctx$.a.b"},
                            "right": {"type": "literal", "value": 2},
                        },
                        {"type": "literal", "value": ""},
                        {"type": "context_path", "path": "$ctx$.c.d"},
                    ],
                }
            ]
        },
    )

    type: Literal["call"]
    name: str
    args: list[ExprNode]


class SelectNode(ASTNode):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "type": "select",
                    "bo": "BB_PREP_SUB",
                    "filter": {"type": "compare", "op": "==", "left": {"type": "context_path", "path": "it.ID"}, "right": {"type": "literal", "value": 1}},
                }
            ]
        },
    )

    type: Literal["select"]
    bo: str
    filter: ExprNode


class SelectOneNode(ASTNode):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "type": "select_one",
                    "bo": "BB_PREP_SUB",
                    "filter": {"type": "compare", "op": "==", "left": {"type": "context_path", "path": "it.ID"}, "right": {"type": "literal", "value": 1}},
                }
            ]
        },
    )

    type: Literal["select_one"]
    bo: str
    filter: ExprNode


class FunctionParamNode(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"name": "OFFERING_ID", "value": {"type": "variable_ref", "name": "oid"}}]})

    name: str
    value: ExprNode


class FetchNode(ASTNode):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"type": "fetch", "name": "E_RT_QUERY", "params": []}]})

    type: Literal["fetch"]
    name: str
    params: list[FunctionParamNode]


class FetchOneNode(ASTNode):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"type": "fetch_one", "name": "E_RT_QUERY", "params": []}]})

    type: Literal["fetch_one"]
    name: str
    params: list[FunctionParamNode]


class ReturnNode(ASTNode):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"type": "return", "value": {"type": "variable_ref", "name": "oid"}}]})

    type: Literal["return"]
    value: ExprNode


ExprNode: TypeAlias = Annotated[
    ContextPathNode
    | LiteralNode
    | VariableRefNode
    | FieldAccessNode
    | MethodCallNode
    | DefNode
    | CompareNode
    | LogicalNode
    | CallNode
    | SelectNode
    | SelectOneNode
    | FetchNode
    | FetchOneNode
    | ReturnNode,
    Field(discriminator="type"),
]


class ProgramNode(ASTNode):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"type": "program", "body": [{"type": "return", "value": {"type": "literal", "value": None}}]}]})

    type: Literal["program"]
    body: list[ExprNode] = Field(min_length=1)


_AST_TYPES = {"ExprNode": ExprNode}

DefNode.model_rebuild(_types_namespace=_AST_TYPES)
FieldAccessNode.model_rebuild(_types_namespace=_AST_TYPES)
MethodCallNode.model_rebuild(_types_namespace=_AST_TYPES)
CompareNode.model_rebuild(_types_namespace=_AST_TYPES)
LogicalNode.model_rebuild(_types_namespace=_AST_TYPES)
CallNode.model_rebuild(_types_namespace=_AST_TYPES)
SelectNode.model_rebuild(_types_namespace=_AST_TYPES)
SelectOneNode.model_rebuild(_types_namespace=_AST_TYPES)
FunctionParamNode.model_rebuild(_types_namespace=_AST_TYPES)
ReturnNode.model_rebuild(_types_namespace=_AST_TYPES)
ProgramNode.model_rebuild(_types_namespace=_AST_TYPES)
