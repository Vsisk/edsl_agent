import json
from typing import Any

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


def inject_expression_comments(expression: str, comments: list[dict[str, Any]]) -> str:
    lines = str(expression or "").splitlines() or [""]
    single_comments: dict[int, list[str]] = {}
    inline_comments: dict[int, list[str]] = {}
    for item in comments:
        if not isinstance(item, dict):
            continue
        text = _sanitize_comment_text(str(item.get("text") or item.get("comment") or ""))
        if not text:
            continue
        line_number = _normalize_line_number(item.get("line"), len(lines))
        placement = str(item.get("placement") or "single").strip().lower()
        if placement == "inline":
            inline_comments.setdefault(line_number, []).append(text)
        elif placement == "single":
            single_comments.setdefault(line_number, []).append(text)

    rendered_lines: list[str] = []
    for index, line in enumerate(lines, start=1):
        for comment in single_comments.get(index, []):
            rendered_lines.append(_generate_block_comment(comment))
        suffixes = inline_comments.get(index, [])
        if suffixes:
            line = f"{line} // {'; '.join(suffixes)}"
        rendered_lines.append(line)
    return "\n".join(rendered_lines)


def generate_expression(node: ASTNode) -> str:
    """Generate canonical EDSL text after comments have been handled by parsing.

    Comments are intentionally not represented as executable AST nodes, so generated
    output cannot accidentally turn explanatory text into part of an expression.
    """
    return _generate_expression(node, None)


def _generate_expression(node: ASTNode, prepend_defs: list[str] | None) -> str:
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
        params = f"({', '.join(node.params)})" if node.params else ""
        if node.render_style == "simple":
            return f"def {node.name}{params}: {_generate_expression(node.value, prepend_defs)};"
        if node.params:
            return f"def {node.name}{params}: {_generate_expression(node.value, prepend_defs)}"
        return f"def {node.name} = {_generate_expression(node.value, prepend_defs)}"
    if isinstance(node, FieldAccessNode):
        return f"{_generate_expression(node.receiver, prepend_defs)}.{node.field}"
    if isinstance(node, MethodCallNode):
        receiver = _generate_expression(node.receiver, prepend_defs)
        if node.lambda_expr is not None:
            return f"{receiver}.{node.name}{{{_generate_expression(node.lambda_expr, prepend_defs)}}}"
        return f"{receiver}.{node.name}({', '.join(_generate_expression(arg, prepend_defs) for arg in node.args)})"
    if isinstance(node, CompareNode):
        return f"{_generate_expression(node.left, prepend_defs)} {node.op} {_generate_expression(node.right, prepend_defs)}"
    if isinstance(node, LogicalNode):
        return f" {node.op} ".join(_generate_expression(item, prepend_defs) for item in node.items).join(("(", ")"))
    if isinstance(node, CallNode):
        if node.name in {"+", "-", "*", "/"} and len(node.args) == 2:
            return f"{_generate_expression(node.args[0], prepend_defs)} {node.name} {_generate_expression(node.args[1], prepend_defs)}"
        if node.name == "__trans_mapping" and len(node.args) == 2:
            return f"[{_generate_expression(node.args[0], prepend_defs).strip(chr(34))}, {_generate_expression(node.args[1], prepend_defs)}]"
        return f"{node.name}({', '.join(_generate_expression(arg, prepend_defs) for arg in node.args)})"
    if isinstance(node, SelectNode):
        return f"select({node.bo}, {_generate_expression(node.filter, prepend_defs)})"
    if isinstance(node, SelectOneNode):
        return f"select_one({node.bo}, {_generate_expression(node.filter, prepend_defs)})"
    if isinstance(node, FetchNode):
        return _generate_fetch("fetch", node.name, node.params, prepend_defs)
    if isinstance(node, FetchOneNode):
        return _generate_fetch("fetch_one", node.name, node.params, prepend_defs)
    if isinstance(node, ReturnNode):
        return _generate_expression(node.value, prepend_defs)
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
        prepend_defs: list[str] = []
        rendered = _generate_expression(item, prepend_defs)
        rendered_lines.extend(prepend_defs)
        if not isinstance(item, CommentNode):
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


def _normalize_line_number(value: Any, line_count: int) -> int:
    try:
        line_number = int(value)
    except (TypeError, ValueError):
        line_number = 1
    return min(max(line_number, 1), line_count)


def _generate_literal(node: LiteralNode) -> str:
    if isinstance(node.value, str):
        return json.dumps(node.value, ensure_ascii=False)
    if isinstance(node.value, bool):
        return "true" if node.value else "false"
    if node.value is None:
        return "null"
    return str(node.value)


def _generate_fetch(
    function_name: str,
    name: str,
    params: list[FunctionParamNode],
    prepend_defs: list[str] | None,
) -> str:
    if not params:
        return f"{function_name}({name})"
    rendered_params = ", ".join(_generate_param(param, prepend_defs) for param in params)
    return f"{function_name}({name}, {rendered_params})"


def _generate_param(
    param: FunctionParamNode,
    prepend_defs: list[str] | None,
) -> str:
    rendered_value = _generate_typed_param_value(param, prepend_defs)
    return f"pair({_normalize_param_name(param.name)}, {rendered_value})"


def _generate_typed_param_value(
    param: FunctionParamNode,
    prepend_defs: list[str] | None,
) -> str:
    rendered_value = _generate_param_value(param)
    if not param.is_list:
        return rendered_value
    variable_name = _list_param_variable_name(param.name)
    if prepend_defs is not None:
        prepend_defs.append(f"def {variable_name} = [{rendered_value}];")
        return variable_name
    return f"[{rendered_value}]"


def _generate_param_value(param: FunctionParamNode) -> str:
    if isinstance(param.value, LiteralNode) and isinstance(param.value.value, str) and _is_char_type(param):
        return _single_quoted_string(param.value.value)
    return _generate_expression(param.value, None)


def _is_char_type(param: FunctionParamNode) -> bool:
    type_name = str(param.data_type_name or "").strip().lower()
    return type_name in {"char", "character", "string", "str"}


def _single_quoted_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _list_param_variable_name(name: str) -> str:
    normalized = "".join(part.title() for part in str(name or "param").split("_") if part)
    if not normalized:
        normalized = "Param"
    return f"{normalized[0].lower()}{normalized[1:]}List"


def _normalize_param_name(name: str) -> str:
    if name.startswith(("it.", "$ctx$", "$local$", "$iter$")):
        return name
    return f"it.{name}"
