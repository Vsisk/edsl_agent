from agent.expression_generation.ast.builder import SimpleExpressionProgramAst


class EDSLRenderer:
    def render_simple_plan(self, program: SimpleExpressionProgramAst) -> str:
        lines = []
        for item in program.definitions:
            params = f"({', '.join(item.params)})" if item.params else ""
            lines.append(_ensure_semicolon(f"def {item.name}{params}: {item.expr}"))
        lines.append(_ensure_semicolon(program.return_expr))
        return "\n".join(lines)


def _ensure_semicolon(line: str) -> str:
    stripped = line.rstrip()
    if stripped.endswith(";"):
        return line
    return f"{stripped};"
