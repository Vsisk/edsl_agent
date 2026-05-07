from typing import Any

from pydantic import TypeAdapter

from agent.expression_generation.ast.nodes import (
    CallNode,
    CompareNode,
    ContextPathNode,
    DefNode,
    ExprNode,
    FetchNode,
    FetchOneNode,
    FunctionParamNode,
    LiteralNode,
    LogicalNode,
    ProgramNode,
    ReturnNode,
    SelectNode,
    SelectOneNode,
    VariableRefNode,
)
from agent.planner.models import (
    CompareExprPlanNode,
    CallExprPlanNode,
    ContextPathExprPlanNode,
    DefExprPlanNode,
    ExprPlanNode,
    FetchExprPlanNode,
    FetchOneExprPlanNode,
    LiteralExprPlanNode,
    LogicalExprPlanNode,
    Plan,
    ReturnExprPlanNode,
    SelectExprPlanNode,
    SelectOneExprPlanNode,
    VariableRefExprPlanNode,
)


def build_ast(plan: Plan | dict[str, Any]) -> ProgramNode:
    plan_model = plan if isinstance(plan, Plan) else Plan.model_validate(plan)
    return ProgramNode(
        type="program",
        body=[_build_node(plan_node) for plan_node in plan_model.nodes],
    )


def _build_node(plan_node: ExprPlanNode) -> ExprNode:
    if isinstance(plan_node, ContextPathExprPlanNode):
        return ContextPathNode(type="context_path", path=plan_node.path)
    if isinstance(plan_node, LiteralExprPlanNode):
        return LiteralNode(type="literal", value=plan_node.value)
    if isinstance(plan_node, VariableRefExprPlanNode):
        return VariableRefNode(type="variable_ref", name=plan_node.name)
    if isinstance(plan_node, DefExprPlanNode):
        return DefNode(type="def", name=plan_node.name, value=_build_node(plan_node.value))
    if isinstance(plan_node, CompareExprPlanNode):
        return CompareNode(
            type="compare",
            op=plan_node.op,
            left=_build_node(plan_node.left),
            right=_build_node(plan_node.right),
        )
    if isinstance(plan_node, LogicalExprPlanNode):
        return LogicalNode(
            type="logical",
            op=plan_node.op,
            items=[_build_node(item) for item in plan_node.items],
        )
    if isinstance(plan_node, CallExprPlanNode):
        return CallNode(
            type="call",
            name=plan_node.name,
            args=[_build_node(arg) for arg in plan_node.args],
        )
    if isinstance(plan_node, SelectExprPlanNode):
        return SelectNode(type="select", bo=plan_node.bo, filter=_build_node(plan_node.filter))
    if isinstance(plan_node, SelectOneExprPlanNode):
        return SelectOneNode(type="select_one", bo=plan_node.bo, filter=_build_node(plan_node.filter))
    if isinstance(plan_node, FetchExprPlanNode):
        return FetchNode(
            type="fetch",
            name=plan_node.name,
            params=[FunctionParamNode(name=param.name, value=_build_node(param.value)) for param in plan_node.params],
        )
    if isinstance(plan_node, FetchOneExprPlanNode):
        return FetchOneNode(
            type="fetch_one",
            name=plan_node.name,
            params=[FunctionParamNode(name=param.name, value=_build_node(param.value)) for param in plan_node.params],
        )
    if isinstance(plan_node, ReturnExprPlanNode):
        return ReturnNode(type="return", value=_build_node(plan_node.value))

    return TypeAdapter(ExprNode).validate_python(plan_node)
