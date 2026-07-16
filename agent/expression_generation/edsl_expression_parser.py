from __future__ import annotations

import json
import re

from agent.expression_generation.expression_syntax import MethodChainParser, split_top_level_commas
from agent.expression_generation.expression_type_validation import SimpleExpressionPlan, _find_binary
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.planner.models import Plan


class EDSLExpressionParser:
    def __init__(self, typed_context: TypedExpressionContext):
        self.function_roots = sorted(
            (item.expr for item in typed_context.root_values if item.source_type == "function"),
            key=len,
            reverse=True,
        )
        self.roots = sorted(
            (item.expr for item in typed_context.root_values if item.source_type != "function"),
            key=len,
            reverse=True,
        )
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
        native_call = self._parse_native_call(expr)
        if native_call is not None:
            return native_call
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
            if root.name.startswith(("$ctx$", "$local$", "$iter$")):
                current = {"type": "context_path", "path": root.name}
            else:
                current = {"type": "variable_ref", "name": root.name}
        return self._append_chain(current, tokens)

    def _parse_native_call(self, expr: str) -> dict | None:
        qualified_name = next(
            (name for name in self.function_roots if expr.startswith(name + "(")),
            None,
        )
        if qualified_name is None:
            return None
        open_paren = len(qualified_name)
        close_paren = self._find_matching_paren(expr, open_paren)
        if close_paren is None:
            raise ValueError(f"unclosed native function call: {qualified_name}")
        raw_args = expr[open_paren + 1:close_paren]
        current = {
            "type": "call",
            "name": qualified_name,
            "args": [
                self.parse_expression(arg)
                for arg in split_top_level_commas(raw_args)
                if arg.strip()
            ],
        }
        suffix = expr[close_paren + 1:].strip()
        if not suffix:
            return current
        if not suffix.startswith("."):
            raise ValueError(f"invalid native function call suffix: {suffix}")
        tokens = MethodChainParser().parse("root" + suffix)[1:]
        return self._append_chain(current, tokens)

    @staticmethod
    def _find_matching_paren(expr: str, open_paren: int) -> int | None:
        depth = 0
        quote = False
        escaped = False
        for index in range(open_paren, len(expr)):
            char = expr[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quote = False
                continue
            if char == '"':
                quote = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
        return None

    def _append_chain(self, current: dict, tokens) -> dict:
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
