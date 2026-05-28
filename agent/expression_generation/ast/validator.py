from agent.expression_generation.ast.nodes import (
    CallNode,
    CompareNode,
    ContextPathNode,
    DefNode,
    FetchNode,
    FetchOneNode,
    LogicalNode,
    ProgramNode,
    ReturnNode,
    SelectNode,
    SelectOneNode,
    VariableRefNode,
)


def validate_ast(program: ProgramNode) -> None:
    for node in program.body:
        _validate_node(node)


def _validate_node(node) -> None:
    if isinstance(node, ContextPathNode):
        if not node.path.strip():
            raise ValueError("context path must not be empty")
        return
    if isinstance(node, VariableRefNode):
        if not node.name.strip():
            raise ValueError("variable ref name must not be empty")
        return
    if isinstance(node, DefNode):
        if not node.name.strip():
            raise ValueError("def name must not be empty")
        _validate_node(node.value)
        return
    if isinstance(node, CompareNode):
        _validate_node(node.left)
        _validate_node(node.right)
        return
    if isinstance(node, LogicalNode):
        if len(node.items) < 2:
            raise ValueError("logical.items must contain at least 2 items")
        for item in node.items:
            _validate_node(item)
        return
    if isinstance(node, CallNode):
        if not node.name.strip():
            raise ValueError("call name must not be empty")
        if node.name == "exists" and len(node.args) != 1:
            raise ValueError("exists call must contain exactly one argument")
        for arg in node.args:
            _validate_node(arg)
        return
    if isinstance(node, (SelectNode, SelectOneNode)):
        if not isinstance(node.filter, (CompareNode, LogicalNode)):
            raise ValueError("select filter must be compare or logical")
        _validate_node(node.filter)
        return
    if isinstance(node, (FetchNode, FetchOneNode)):
        _validate_fetch_params(node.params)
        for param in node.params:
            _validate_node(param.value)
        return
    if isinstance(node, ReturnNode):
        if node.value is None:
            raise ValueError("return must contain value")
        _validate_node(node.value)


def _validate_fetch_params(params) -> None:
    seen: set[str] = set()
    for param in params:
        if param.name in seen:
            raise ValueError(f"duplicate fetch param: {param.name}")
        seen.add(param.name)
