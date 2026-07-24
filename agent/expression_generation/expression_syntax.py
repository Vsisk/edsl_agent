from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChainToken(BaseModel):
    token_type: Literal["root", "field", "method_call", "lambda_method_call"]
    raw: str
    name: str
    args: list[str] = Field(default_factory=list)
    lambda_expr: str | None = None


class ExpressionTokenizer:
    def split_top_level(self, expr: str, separator: str) -> list[str]:
        result: list[str] = []
        start = 0
        quote: str | None = None
        escape = False
        parens = braces = 0
        for index, char in enumerate(expr):
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    quote = None
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == "(":
                parens += 1
            elif char == ")":
                parens -= 1
            elif char == "{":
                braces += 1
            elif char == "}":
                braces -= 1
            elif char == separator and parens == 0 and braces == 0:
                if separator == "." and index > 0 and index + 1 < len(expr):
                    if expr[index - 1].isdigit() and expr[index + 1].isdigit():
                        continue
                result.append(expr[start:index].strip())
                start = index + 1
        result.append(expr[start:].strip())
        return result


class TopLevelDotSplitter:
    def split(self, expr: str) -> list[str]:
        return ExpressionTokenizer().split_top_level(expr, ".")


def split_top_level_dot_chain(expr: str) -> list[str]:
    return TopLevelDotSplitter().split(expr)


def split_top_level_commas(expr: str) -> list[str]:
    if not expr.strip():
        return []
    return ExpressionTokenizer().split_top_level(expr, ",")


class MethodChainParser:
    def parse(self, expr: str) -> list[ChainToken]:
        pieces = split_top_level_dot_chain(expr)
        result: list[ChainToken] = []
        for index, raw in enumerate(pieces):
            if index == 0:
                result.append(ChainToken(token_type="root", raw=raw, name=raw))
                continue
            brace = raw.find("{")
            if brace > 0 and raw.endswith("}"):
                result.append(ChainToken(
                    token_type="lambda_method_call", raw=raw, name=raw[:brace].strip(),
                    lambda_expr=raw[brace + 1:-1].strip(),
                ))
                continue
            paren = raw.find("(")
            if paren > 0 and raw.endswith(")"):
                result.append(ChainToken(
                    token_type="method_call", raw=raw, name=raw[:paren].strip(),
                    args=split_top_level_commas(raw[paren + 1:-1]),
                ))
                continue
            result.append(ChainToken(token_type="field", raw=raw, name=raw))
        return result
