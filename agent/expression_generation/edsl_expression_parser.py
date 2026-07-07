from __future__ import annotations

import json
import re

from agent.expression_generation.expression_syntax import MethodChainParser, split_top_level_commas
from agent.expression_generation.expression_type_validation import SimpleExpressionPlan, _find_binary
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.planner.models import Plan


class EDSLExpressionParser:
    def __init__(self, typed_context: TypedExpressionContext):
        self.roots = sorted((item.expr for item in typed_context.root_values), key=len, reverse=True)
        self.variables: set[str] = {"it"}

    def parse_plan(self, simple_plan: SimpleExpressionPlan) -> Plan:
        nodes: list[dict] = []
        for definition in simple_plan.definitions:
            value = self.parse_expression(definition.expr)
            nodes.append({"type": "def", "name": definition.name, "value": value, "render_style": "simple"})
            self.variables.add(definition.name)
        nodes.append({"type": "return", "value": self.parse_expression(simple_plan.return_expr)})
        return Plan.model_validate({"nodes": nodes})

    def parse_expression(self, expr: str) -> dict:
        expr = expr.strip()
        if len(expr) >= 2 and expr[0] == expr[-1] == '"':
            return {"type": "literal", "value": json.loads(expr)}
        if expr in {"true", "false"}:
            return {"type": "literal", "value": expr == "true"}
        if re.fullmatch(r"-?\d+", expr):
            return {"type": "literal", "value": int(expr)}
        if re.fullmatch(r"-?\d+\.\d+", expr):
            return {"type": "literal", "value": float(expr)}
        if expr.lower().startswith("if(") and expr.endswith(")"):
            return {"type": "call", "name": "if", "args": [self.parse_expression(arg) for arg in split_top_level_commas(expr[3:-1])]}
        binary = _find_binary(expr)
        if binary:
            left, op, right = binary
            if op in {"&&", "||"}:
                return {"type": "logical", "op": "and" if op == "&&" else "or",
                        "items": [self.parse_expression(left), self.parse_expression(right)]}
            if op in {"==", "!=", ">", ">=", "<", "<="}:
                return {"type": "compare", "op": op, "left": self.parse_expression(left), "right": self.parse_expression(right)}
            return {"type": "call", "name": op, "args": [self.parse_expression(left), self.parse_expression(right)]}
        fetch = re.match(r"^(fetch_one|fetch)\((.*)\)$", expr)
        if fetch:
            args = split_top_level_commas(fetch.group(2))
            params = []
            for raw in args[1:]:
                pair = re.match(r"^pair\((.*)\)$", raw)
                if not pair:
                    raise ValueError(f"invalid fetch parameter: {raw}")
                pair_args = split_top_level_commas(pair.group(1))
                if len(pair_args) != 2:
                    raise ValueError(f"invalid pair: {raw}")
                params.append({"name": pair_args[0], "value": self.parse_expression(pair_args[1])})
            return {"type": fetch.group(1), "name": args[0], "params": params}
        return self._parse_chain(expr)

    def _parse_chain(self, expr: str) -> dict:
        root_expr = next((root for root in self.roots if expr == root or expr.startswith(root + ".")), None)
        if root_expr:
            current: dict = {"type": "context_path", "path": root_expr}
            remainder = expr[len(root_expr):].lstrip(".")
            tokens = MethodChainParser().parse("root" + ("." + remainder if remainder else ""))[1:]
        else:
            tokens = MethodChainParser().parse(expr)
            root = tokens.pop(0)
            if root.name.startswith(("$ctx$", "$local$")):
                current = {"type": "context_path", "path": root.name}
            else:
                current = {"type": "variable_ref", "name": root.name}
        for token in tokens:
            if token.token_type == "field":
                current = {"type": "field_access", "receiver": current, "field": token.name}
            elif token.token_type == "lambda_method_call":
                current = {"type": "method_call", "receiver": current, "name": token.name,
                           "args": [], "lambda_expr": self.parse_expression(token.lambda_expr or "")}
            else:
                current = {"type": "method_call", "receiver": current, "name": token.name,
                           "args": [self.parse_expression(arg) for arg in token.args], "lambda_expr": None}
        return current
