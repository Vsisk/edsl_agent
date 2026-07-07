from __future__ import annotations

from typing import Annotated, Literal, TypeAlias
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _ExprPlanBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextPathExprPlanNode(_ExprPlanBaseModel):
    type: Literal["context_path"]
    path: str


class LiteralExprPlanNode(_ExprPlanBaseModel):
    type: Literal["literal"]
    value: str | int | float | bool | None


class VariableRefExprPlanNode(_ExprPlanBaseModel):
    type: Literal["variable_ref"]
    name: str


class FieldAccessExprPlanNode(_ExprPlanBaseModel):
    type: Literal["field_access"]
    receiver: ExprPlanNode
    field: str


class MethodCallExprPlanNode(_ExprPlanBaseModel):
    type: Literal["method_call"]
    receiver: ExprPlanNode
    name: str
    args: list[ExprPlanNode] = Field(default_factory=list)
    lambda_expr: ExprPlanNode | None = None


class DefExprPlanNode(_ExprPlanBaseModel):
    type: Literal["def"]
    name: str
    value: ExprPlanNode
    render_style: Literal["legacy", "simple"] = "legacy"


class CompareExprPlanNode(_ExprPlanBaseModel):
    type: Literal["compare"]
    op: Literal["==", "!=", ">", ">=", "<", "<="]
    left: ExprPlanNode
    right: ExprPlanNode


class LogicalExprPlanNode(_ExprPlanBaseModel):
    type: Literal["logical"]
    op: Literal["and", "or"]
    items: list[ExprPlanNode] = Field(min_length=2)


class CallExprPlanNode(_ExprPlanBaseModel):
    """A generic function call expression, such as IF(condition, then_value, else_value)."""

    type: Literal["call"]
    name: str = Field(description="Function name to call, for example IF, NVL, CONCAT, FORMAT_DATE, exists.")
    args: list[ExprPlanNode] = Field(
        description="Ordered function arguments. Each argument is a recursive ExprPlanNode."
    )


class SelectExprPlanNode(_ExprPlanBaseModel):
    type: Literal["select"]
    bo: str
    filter: ExprPlanNode


class SelectOneExprPlanNode(_ExprPlanBaseModel):
    type: Literal["select_one"]
    bo: str
    filter: ExprPlanNode


class FetchParam(_ExprPlanBaseModel):
    name: str
    value: ExprPlanNode


class FetchExprPlanNode(_ExprPlanBaseModel):
    type: Literal["fetch"]
    name: str
    params: list[FetchParam]


class FetchOneExprPlanNode(_ExprPlanBaseModel):
    type: Literal["fetch_one"]
    name: str
    params: list[FetchParam]


class ReturnExprPlanNode(_ExprPlanBaseModel):
    type: Literal["return"]
    value: ExprPlanNode


class Plan(_ExprPlanBaseModel):
    nodes: list[ExprPlanNode] = Field(min_length=1)


ExprPlanNode: TypeAlias = Annotated[
    ContextPathExprPlanNode
    | LiteralExprPlanNode
    | VariableRefExprPlanNode
    | FieldAccessExprPlanNode
    | MethodCallExprPlanNode
    | DefExprPlanNode
    | CompareExprPlanNode
    | LogicalExprPlanNode
    | CallExprPlanNode
    | SelectExprPlanNode
    | SelectOneExprPlanNode
    | FetchExprPlanNode
    | FetchOneExprPlanNode
    | ReturnExprPlanNode,
    Field(discriminator="type"),
]


_EXPR_PLAN_TYPES = {
    "ExprPlanNode": ExprPlanNode,
}

DefExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
FieldAccessExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
MethodCallExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
CompareExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
LogicalExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
CallExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
SelectExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
SelectOneExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
FetchParam.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
ReturnExprPlanNode.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)
Plan.model_rebuild(_types_namespace=_EXPR_PLAN_TYPES)

EXPR_PLAN_NODE_SCHEMA = TypeAdapter(ExprPlanNode).json_schema()
PLAN_SCHEMA = Plan.model_json_schema()


def _legacy_schema_without_member_nodes(value):
    excluded = {"#/$defs/FieldAccessExprPlanNode", "#/$defs/MethodCallExprPlanNode"}
    if isinstance(value, list):
        return [
            _legacy_schema_without_member_nodes(item)
            for item in value
            if not (isinstance(item, dict) and item.get("$ref") in excluded)
        ]
    if isinstance(value, dict):
        return {
            key: _legacy_schema_without_member_nodes(item)
            for key, item in value.items()
            if not (key in {"FieldAccessExprPlanNode", "MethodCallExprPlanNode"} and "$defs" not in value)
        }
    return value


LEGACY_PLAN_SCHEMA = _legacy_schema_without_member_nodes(deepcopy(PLAN_SCHEMA))
