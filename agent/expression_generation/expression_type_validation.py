from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from agent.expression_generation.expression_syntax import MethodChainParser, split_top_level_commas
from agent.expression_generation.type_system import MethodRegistry, TypeRef, TypeRegistry
from agent.expression_generation.typed_context import TypedExpressionContext


BOOLEAN = TypeRef(kind="basic", name="boolean")
STRING = TypeRef(kind="basic", name="String")
INT = TypeRef(kind="basic", name="int")
LONG = TypeRef(kind="basic", name="long")
DECIMAL = TypeRef(kind="basic", name="decimal")


class SimpleDefinition(BaseModel):
    name: str
    expr: str


class SimpleExpressionPlan(BaseModel):
    definitions: list[SimpleDefinition] = Field(default_factory=list)
    return_expr: str
    target_return_type: TypeRef | None = None


class TypeValidationError(BaseModel):
    error_type: str
    expr: str
    token: str | None = None
    owner_type: TypeRef | None = None
    expected_type: TypeRef | None = None
    actual_type: TypeRef | None = None
    message: str


class ExpressionValidationResult(BaseModel):
    return_type: TypeRef | None = None
    errors: list[TypeValidationError] = Field(default_factory=list)
    definition_types: dict[str, TypeRef] = Field(default_factory=dict)

    @computed_field
    @property
    def is_valid(self) -> bool:
        return not self.errors


class ExpressionValidationInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    typed_context: TypedExpressionContext
    type_registry: TypeRegistry
    method_registry: MethodRegistry


class TypeScope:
    def __init__(self, parent: "TypeScope | None" = None):
        self.parent = parent
        self.values: dict[str, TypeRef] = {}

    def bind(self, name: str, type_ref: TypeRef) -> None:
        self.values[name] = type_ref

    def resolve(self, name: str) -> TypeRef | None:
        return self.values.get(name) or (self.parent.resolve(name) if self.parent else None)


class ExpressionTypeResolver:
    def __init__(self, validation_input: ExpressionValidationInput, errors: list[TypeValidationError]):
        self.input = validation_input
        self.errors = errors
        self.roots = {
            root.expr: parse_type_text(root.return_type)
            for root in validation_input.typed_context.root_values
        }

    def resolve(self, expr: str, scope: TypeScope) -> TypeRef | None:
        expr = expr.strip()
        literal = _literal_type(expr)
        if literal is not None:
            return literal
        if expr.lower().startswith("if(") and expr.endswith(")"):
            return self._resolve_if(expr, scope)
        binary = _find_binary(expr)
        if binary is not None:
            left, op, right = binary
            return self._resolve_binary(expr, left, op, right, scope)
        fetch_type = self._resolve_fetch(expr)
        if fetch_type is not None:
            return fetch_type
        return self._resolve_chain(expr, scope)

    def _resolve_if(self, expr: str, scope: TypeScope) -> TypeRef | None:
        args = split_top_level_commas(expr[3:-1])
        if len(args) != 3:
            self._error("UNKNOWN_ROOT", expr, expr, "if requires three arguments")
            return None
        condition = self.resolve(args[0], scope)
        then_type = self.resolve(args[1], scope)
        else_type = self.resolve(args[2], scope)
        if condition is not None and condition != BOOLEAN:
            self._error("IF_CONDITION_NOT_BOOLEAN", expr, args[0], "if condition must be boolean", expected=BOOLEAN, actual=condition)
        if then_type is not None and else_type is not None and then_type != else_type:
            self._error("IF_BRANCH_TYPE_MISMATCH", expr, None, "if branches must have the same type", expected=then_type, actual=else_type)
            return None
        return then_type if condition == BOOLEAN and then_type == else_type else None

    def _resolve_binary(self, expr: str, left_expr: str, op: str, right_expr: str, scope: TypeScope) -> TypeRef | None:
        left, right = self.resolve(left_expr, scope), self.resolve(right_expr, scope)
        if left is None or right is None:
            return None
        if op in {">", "<", ">=", "<=", "==", "!="}:
            if op in {">", "<", ">=", "<="} and not (_numeric(left) and _numeric(right)):
                self._error("METHOD_ARG_TYPE_MISMATCH", expr, op, "comparison operands must be numeric", expected=left, actual=right)
                return None
            return BOOLEAN
        if op in {"&&", "||"}:
            if left != BOOLEAN or right != BOOLEAN:
                self._error("METHOD_ARG_TYPE_MISMATCH", expr, op, "boolean operator requires boolean operands", expected=BOOLEAN, actual=right)
                return None
            return BOOLEAN
        if _numeric(left) and _numeric(right):
            return max((left, right), key=lambda item: _numeric_rank(item))
        self._error("METHOD_ARG_TYPE_MISMATCH", expr, op, "arithmetic operands must be numeric", owner=left, actual=right)
        return None

    def _resolve_fetch(self, expr: str) -> TypeRef | None:
        match = re.match(r"^(fetch_one|fetch)\s*\(\s*([^,\)]+)", expr)
        if not match:
            return None
        kind, name = match.group(1), match.group(2).strip()
        for template in self.input.typed_context.var_templates:
            candidate = re.match(r"^(fetch_one|fetch)\s*\(\s*([^,\)]+)", template.definition_expr)
            if candidate and candidate.group(1) == kind and candidate.group(2).strip() == name:
                return parse_type_text(template.return_type)
        self._error("UNKNOWN_ROOT", expr, match.group(0), f"unknown {kind} source")
        return None

    def _resolve_chain(self, expr: str, scope: TypeScope) -> TypeRef | None:
        root_expr = next((root for root in sorted(self.roots, key=len, reverse=True) if expr == root or expr.startswith(root + ".")), None)
        if root_expr:
            current = self.roots[root_expr]
            remainder = expr[len(root_expr):].lstrip(".")
            tokens = MethodChainParser().parse("root" + ("." + remainder if remainder else ""))[1:]
        else:
            tokens = MethodChainParser().parse(expr)
            root = tokens.pop(0)
            if root.name.startswith(("$ctx$", "$local$")):
                self._error("UNKNOWN_CONTEXT_PATH", expr, root.raw, "unknown context path")
                return None
            current = scope.resolve(root.name)
            if current is None:
                code = "UNKNOWN_ROOT" if "(" in root.name else "UNKNOWN_VARIABLE"
                self._error(code, expr, root.raw, "unknown expression root")
                return None
        for token in tokens:
            if token.token_type == "field":
                if current.kind == "basic":
                    self._error("FIELD_ACCESS_ON_BASIC_TYPE", expr, token.raw, "cannot access a field on a basic type", owner=current)
                    return None
                if current.kind == "list":
                    self._error("LIST_FIELD_ACCESS_WITHOUT_ELEMENT_METHOD", expr, token.raw, "list fields require first/find/findAll", owner=current)
                    return None
                field_type = self.input.type_registry.resolve_field(current, token.name)
                if field_type is None:
                    self._error("FIELD_NOT_FOUND", expr, token.raw, "field not found", owner=current)
                    return None
                current = field_type
            elif token.token_type == "lambda_method_call":
                if current.kind != "list" or current.element_type is None:
                    self._error("LAMBDA_IT_TYPE_NOT_FOUND", expr, token.raw, "lambda it type is unavailable", owner=current)
                    return None
                child = TypeScope(scope); child.bind("it", current.element_type)
                body_type = self.resolve(token.lambda_expr or "", child)
                if body_type != BOOLEAN:
                    self._error("LAMBDA_EXPR_NOT_BOOLEAN", expr, token.raw, "lambda expression must be boolean", expected=BOOLEAN, actual=body_type)
                    return None
                matched = self.input.method_registry.match(current, token.name + "{expr}", [])
                if matched is None:
                    self._error("METHOD_NOT_FOUND", expr, token.raw, "lambda method not found", owner=current)
                    return None
                current = matched
            else:
                arg_types = [self.resolve(arg, scope) for arg in token.args]
                if any(arg is None for arg in arg_types):
                    return None
                methods = [method for method in self.input.method_registry.methods_for(current) if method.name == token.name]
                if not methods:
                    self._error("METHOD_NOT_FOUND", expr, token.raw, "method not found", owner=current)
                    return None
                if not any(len(method.arg_types) == len(arg_types) for method in methods):
                    self._error("METHOD_ARG_COUNT_MISMATCH", expr, token.raw, "method argument count mismatch", owner=current)
                    return None
                matched = self.input.method_registry.match(current, token.name, [arg for arg in arg_types if arg is not None])
                if matched is None:
                    self._error("METHOD_ARG_TYPE_MISMATCH", expr, token.raw, "method argument type mismatch", owner=current)
                    return None
                current = matched
        return current

    def _error(self, code: str, expr: str, token: str | None, message: str, *, owner=None, expected=None, actual=None) -> None:
        self.errors.append(TypeValidationError(error_type=code, expr=expr, token=token, owner_type=owner, expected_type=expected, actual_type=actual, message=message))


class MethodChainValidator:
    def __init__(self, validation_input: ExpressionValidationInput):
        self.input = validation_input

    def validate(self, plan: SimpleExpressionPlan) -> ExpressionValidationResult:
        errors: list[TypeValidationError] = []
        resolver = ExpressionTypeResolver(self.input, errors)
        scope = TypeScope()
        definition_types: dict[str, TypeRef] = {}
        for definition in plan.definitions:
            type_ref = resolver.resolve(definition.expr, scope)
            if type_ref is not None:
                scope.bind(definition.name, type_ref); definition_types[definition.name] = type_ref
        return_type = resolver.resolve(plan.return_expr, scope)
        if return_type is not None and plan.target_return_type is not None and return_type != plan.target_return_type:
            errors.append(TypeValidationError(error_type="TARGET_RETURN_TYPE_MISMATCH", expr=plan.return_expr, expected_type=plan.target_return_type, actual_type=return_type, message="return type does not match target"))
        return ExpressionValidationResult(return_type=return_type, errors=errors, definition_types=definition_types)


def parse_type_text(text: str) -> TypeRef:
    text = text.strip()
    if text.startswith("List<") and text.endswith(">"):
        return TypeRef(kind="list", element_type=parse_type_text(text[5:-1]))
    if text.startswith("Map<") and text.endswith(">"):
        parts = split_top_level_commas(text[4:-1])
        return TypeRef(kind="map", key_type=parse_type_text(parts[0]), value_type=parse_type_text(parts[1]))
    if "." in text:
        kind, name = text.split(".", 1)
        return TypeRef(kind=kind, name=name)
    return TypeRef(kind=text if text in {"void", "unknown"} else "unknown")


def _literal_type(expr: str) -> TypeRef | None:
    if len(expr) >= 2 and expr[0] == expr[-1] == '"': return STRING
    if expr in {"true", "false"}: return BOOLEAN
    if re.fullmatch(r"-?\d+", expr): return INT
    if re.fullmatch(r"-?\d+\.\d+", expr): return DECIMAL
    return None


def _find_binary(expr: str) -> tuple[str, str, str] | None:
    groups = [["||"], ["&&"], ["==", "!=", ">=", "<=", ">", "<"], ["+", "-"], ["*", "/"]]
    quote = escape = False; parens = braces = 0
    positions: list[tuple[int, str, int]] = []
    index = 0
    while index < len(expr):
        char = expr[index]
        if quote:
            if escape: escape = False
            elif char == "\\": escape = True
            elif char == '"': quote = False
            index += 1; continue
        if char == '"': quote = True; index += 1; continue
        if char == "(": parens += 1
        elif char == ")": parens -= 1
        elif char == "{": braces += 1
        elif char == "}": braces -= 1
        if parens == 0 and braces == 0:
            for precedence, ops in enumerate(groups):
                op = next((item for item in ops if expr.startswith(item, index)), None)
                if op and index > 0:
                    positions.append((precedence, op, index)); index += len(op) - 1; break
        index += 1
    if not positions: return None
    precedence, op, at = min(positions, key=lambda item: (item[0], -item[2]))
    return expr[:at].strip(), op, expr[at + len(op):].strip()


def _numeric(type_ref: TypeRef) -> bool:
    return type_ref.kind == "basic" and (type_ref.name or "").lower() in {"int", "int32", "long", "int64", "decimal", "double", "float"}


def _numeric_rank(type_ref: TypeRef) -> int:
    return {"int": 1, "int32": 1, "long": 2, "int64": 2, "decimal": 3, "double": 3, "float": 3}.get((type_ref.name or "").lower(), 0)
