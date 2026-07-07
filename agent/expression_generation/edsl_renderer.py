from agent.expression_generation.ast.builder import SimpleExpressionProgramAst


class EDSLRenderer:
    def render_simple_plan(self, program: SimpleExpressionProgramAst) -> str:
        lines = [f"def {item.name}: {item.expr};" for item in program.definitions]
        lines.append(program.return_expr)
        return "\n".join(lines)
