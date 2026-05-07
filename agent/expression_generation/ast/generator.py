import json

from agent.expression_generation.ast.nodes import ASTNode
from agent.expression_generation.ast.nodes import (
    CallNode,
    CompareNode,
    ContextPathNode,
    DefNode,
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


def generate_expression(node: ASTNode) -> str:
    if isinstance(node, ProgramNode):
        return "\n".join(generate_expression(item) for item in node.body)
    if isinstance(node, ContextPathNode):
        return node.path
    if isinstance(node, LiteralNode):
        return _generate_literal(node)
    if isinstance(node, VariableRefNode):
        return node.name
    if isinstance(node, DefNode):
        return f"def {node.name} = {generate_expression(node.value)}"
    if isinstance(node, CompareNode):
        return f"{generate_expression(node.left)} {node.op} {generate_expression(node.right)}"
    if isinstance(node, LogicalNode):
        return f" {node.op} ".join(generate_expression(item) for item in node.items).join(("(", ")"))
    if isinstance(node, CallNode):
        return f"{node.name}({', '.join(generate_expression(arg) for arg in node.args)})"
    if isinstance(node, SelectNode):
        return f"select({node.bo}, {generate_expression(node.filter)})"
    if isinstance(node, SelectOneNode):
        return f"select_one({node.bo}, {generate_expression(node.filter)})"
    if isinstance(node, FetchNode):
        return _generate_fetch("fetch", node.name, node.params)
    if isinstance(node, FetchOneNode):
        return _generate_fetch("fetch_one", node.name, node.params)
    if isinstance(node, ReturnNode):
        return generate_expression(node.value)
    raise TypeError(f"Unsupported AST node: {type(node).__name__}")


def _generate_literal(node: LiteralNode) -> str:
    if isinstance(node.value, str):
        return json.dumps(node.value, ensure_ascii=False)
    if isinstance(node.value, bool):
        return "true" if node.value else "false"
    if node.value is None:
        return "null"
    return str(node.value)


def _generate_fetch(function_name: str, name: str, params: list[FunctionParamNode]) -> str:
    if not params:
        return f"{function_name}({name})"
    rendered_params = ", ".join(_generate_param(param) for param in params)
    return f"{function_name}({name}, {rendered_params})"


def _generate_param(param: FunctionParamNode) -> str:
    return f"pair({_normalize_param_name(param.name)}, {generate_expression(param.value)})"


def _normalize_param_name(name: str) -> str:
    if name.startswith(("it.", "$ctx$", "$local$", "$iter$")):
        return name
    return f"it.{name}"
