import json

from agent.expression_generation.ast.nodes import ASTNode
from agent.expression_generation.ast.nodes import (
    CallNode,
    CommentNode,
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
    FieldAccessNode,
    MethodCallNode,
)


def inject_expression_comment(expression: str, comment: str, *, style: str = "line") -> str:
    """Prefix generated expression text with an EDSL line or block comment."""
    if style == "line":
        rendered_comment = "\n".join(f"// {line}" for line in comment.splitlines() or [""])
    elif style == "block":
        if "*/" in comment:
            raise ValueError("block comment must not contain */")
        rendered_comment = f"/* {comment} */"
    else:
        raise ValueError("comment style must be 'line' or 'block'")
    return f"{rendered_comment}\n{expression}"


def generate_expression(node: ASTNode) -> str:
    """Generate canonical EDSL text after comments have been handled by parsing.

    Comments are intentionally not represented as executable AST nodes, so generated
    output cannot accidentally turn explanatory text into part of an expression.
    """
    if isinstance(node, ProgramNode):
        return _join_program_lines(node)
    if isinstance(node, CommentNode):
        return _generate_block_comment(node.text)
    if isinstance(node, ContextPathNode):
        return node.path
    if isinstance(node, LiteralNode):
        return _generate_literal(node)
    if isinstance(node, VariableRefNode):
        return node.name
    if isinstance(node, DefNode):
        if node.render_style == "simple":
            return f"def {node.name}: {generate_expression(node.value)};"
        return f"def {node.name} = {generate_expression(node.value)}"
    if isinstance(node, FieldAccessNode):
        return f"{generate_expression(node.receiver)}.{node.field}"
    if isinstance(node, MethodCallNode):
        receiver = generate_expression(node.receiver)
        if node.lambda_expr is not None:
            return f"{receiver}.{node.name}{{{generate_expression(node.lambda_expr)}}}"
        return f"{receiver}.{node.name}({', '.join(generate_expression(arg) for arg in node.args)})"
    if isinstance(node, CompareNode):
        return f"{generate_expression(node.left)} {node.op} {generate_expression(node.right)}"
    if isinstance(node, LogicalNode):
        return f" {node.op} ".join(generate_expression(item) for item in node.items).join(("(", ")"))
    if isinstance(node, CallNode):
        if node.name in {"+", "-", "*", "/"} and len(node.args) == 2:
            return f"{generate_expression(node.args[0])} {node.name} {generate_expression(node.args[1])}"
        if node.name == "__trans_mapping" and len(node.args) == 2:
            return f"[{generate_expression(node.args[0]).strip(chr(34))}, {generate_expression(node.args[1])}]"
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


def _join_program_lines(node: ProgramNode) -> str:
    rendered_lines: list[str] = []
    pending_inline_comments: list[str] = []
    for item in node.body:
        if isinstance(item, CommentNode):
            if item.placement == "inline":
                pending_inline_comments.append(_sanitize_comment_text(item.text))
            else:
                rendered_lines.append(_generate_block_comment(item.text))
            continue
        rendered = generate_expression(item)
        if not isinstance(item, ReturnNode):
            rendered = _ensure_semicolon(rendered)
        if pending_inline_comments:
            rendered = f"{rendered} // {'; '.join(pending_inline_comments)}"
            pending_inline_comments = []
        rendered_lines.append(rendered)
    for comment in pending_inline_comments:
        rendered_lines.append(_generate_block_comment(comment))
    return "\n".join(rendered_lines)


def _generate_block_comment(text: str) -> str:
    return f"/* {_sanitize_comment_text(text)} */"


def _sanitize_comment_text(text: str) -> str:
    return str(text or "").replace("/*", "").replace("*/", "").replace("//", "").strip()


def _ensure_semicolon(line: str) -> str:
    stripped = line.rstrip()
    if stripped.endswith(";"):
        return line
    return f"{stripped};"


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
