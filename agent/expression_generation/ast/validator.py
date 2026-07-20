from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from agent.expression_generation.ast.nodes import (
    CallNode,
    CompareNode,
    ContextPathNode,
    DefNode,
    FetchNode,
    FetchOneNode,
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
from agent.expression_generation.type_system import (
    FunctionTypeRegistry,
    MethodRegistry,
    TypeRef,
    TypeRegistry,
    create_builtin_function_type_registry,
    normalize_return_type,
)


@dataclass(slots=True)
class AstValidationContext:
    context_registry: Mapping[str, Any] = field(default_factory=dict)
    context_types: Mapping[str, TypeRef] = field(default_factory=dict)
    function_types: Mapping[str, TypeRef] = field(default_factory=dict)
    fetch_return_types: Mapping[str, TypeRef] = field(default_factory=dict)
    type_registry: TypeRegistry | None = None
    method_registry: MethodRegistry | None = None
    variable_types: Mapping[str, TypeRef] = field(default_factory=dict)
    function_type_registry: FunctionTypeRegistry = field(
        default_factory=create_builtin_function_type_registry
    )


class AstValidationResult(BaseModel):
    is_valid: bool
    return_type: TypeRef | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(slots=True)
class _ValidationState:
    context: AstValidationContext | None
    variable_types: dict[str, TypeRef] = field(default_factory=dict)


def validate_ast(program: ProgramNode, validation_context: AstValidationContext | None = None) -> None:
    result = validate_ast_with_result(program, validation_context)
    if not result.is_valid:
        message = result.errors[0]["message"] if result.errors else "invalid ast"
        raise ValueError(message)


def validate_ast_with_result(
    program: ProgramNode,
    validation_context: AstValidationContext | None = None,
) -> AstValidationResult:
    try:
        return_type = infer_ast_return_type(program, validation_context)
    except (ValueError, TypeError) as exc:
        return AstValidationResult(
            is_valid=False,
            errors=[
                {
                    "error_type": "AST_VALIDATION_FAILED",
                    "message": " ".join(str(exc).split()),
                }
            ],
        )
    return AstValidationResult(is_valid=True, return_type=return_type, errors=[])


def infer_ast_return_type(
    program: ProgramNode,
    validation_context: AstValidationContext | None = None,
) -> TypeRef | None:
    state = _ValidationState(
        context=validation_context,
        variable_types=dict(validation_context.variable_types) if validation_context is not None else {},
    )
    return_type: TypeRef | None = None
    for node in program.body:
        inferred = _validate_node(node, state)
        if isinstance(node, ReturnNode):
            return_type = inferred
    return return_type


def _validate_node(node, state: _ValidationState | None = None) -> TypeRef | None:
    state = state or _ValidationState(context=None)
    if isinstance(node, ContextPathNode):
        if not node.path.strip():
            raise ValueError("context path must not be empty")
        return _infer_context_path_type(node.path, state)
    if isinstance(node, VariableRefNode):
        if not node.name.strip():
            raise ValueError("variable ref name must not be empty")
        return state.variable_types.get(node.name)
    if isinstance(node, LiteralNode):
        return _infer_literal_type(node.value)
    if isinstance(node, FieldAccessNode):
        if not node.field.strip():
            raise ValueError("field name must not be empty")
        receiver_type = _validate_node(node.receiver, state)
        return _resolve_field_type(receiver_type, node.field, state)
    if isinstance(node, MethodCallNode):
        if not node.name.strip():
            raise ValueError("method name must not be empty")
        receiver_type = _validate_node(node.receiver, state)
        arg_types = []
        for arg in node.args:
            arg_types.append(_validate_node(arg, state))
        if node.lambda_expr is not None:
            lambda_state = state
            if receiver_type is not None and receiver_type.kind == "list" and receiver_type.element_type is not None:
                lambda_state = _ValidationState(
                    context=state.context,
                    variable_types={**state.variable_types, "it": receiver_type.element_type},
                )
            _validate_node(node.lambda_expr, lambda_state)
            return _resolve_method_type(receiver_type, f"{node.name}{{expr}}", [], state)
        return _resolve_method_type(receiver_type, node.name, arg_types, state)
    if isinstance(node, DefNode):
        if not node.name.strip():
            raise ValueError("def name must not be empty")
        value_type = _validate_node(node.value, state)
        if value_type is not None:
            state.variable_types[node.name] = value_type
        return value_type
    if isinstance(node, CompareNode):
        _validate_node(node.left, state)
        _validate_node(node.right, state)
        return TypeRef(kind="basic", name="boolean")
    if isinstance(node, LogicalNode):
        if len(node.items) < 2:
            raise ValueError("logical.items must contain at least 2 items")
        for item in node.items:
            _validate_node(item, state)
        return TypeRef(kind="basic", name="boolean")
    if isinstance(node, CallNode):
        if not node.name.strip():
            raise ValueError("call name must not be empty")
        if node.name == "exists" and len(node.args) != 1:
            raise ValueError("exists call must contain exactly one argument")
        if node.name in {"find", "find_all"}:
            return _infer_list_search_call_type(node, state)
        arg_types = [_validate_node(arg, state) for arg in node.args]
        if node.name == "if":
            return _infer_if_call_type(node, arg_types)
        if state.context is not None and node.name in state.context.function_types:
            return state.context.function_types[node.name]
        if state.context is not None and all(arg_type is not None for arg_type in arg_types):
            matched = state.context.function_type_registry.match(
                node.name, [arg_type for arg_type in arg_types if arg_type is not None]
            )
            if matched is not None:
                return matched
            if state.context.function_type_registry.has_function(node.name):
                raise ValueError(f"function arguments do not match signature: {node.name}")
        return None
    if isinstance(node, (SelectNode, SelectOneNode)):
        if not isinstance(node.filter, (CompareNode, LogicalNode)):
            raise ValueError("select filter must be compare or logical")
        _validate_node(node.filter, state)
        return None
    if isinstance(node, (FetchNode, FetchOneNode)):
        _validate_fetch_params(node.params)
        for param in node.params:
            _validate_node(param.value, state)
        if state.context is not None:
            return state.context.fetch_return_types.get(node.name)
        return None
    if isinstance(node, ReturnNode):
        if node.value is None:
            raise ValueError("return must contain value")
        return _validate_node(node.value, state)
    return None


def _infer_literal_type(value: Any) -> TypeRef:
    if isinstance(value, bool):
        return TypeRef(kind="basic", name="boolean")
    if isinstance(value, int) and not isinstance(value, bool):
        return TypeRef(kind="basic", name="int")
    if isinstance(value, float):
        return TypeRef(kind="basic", name="double")
    if isinstance(value, str):
        return TypeRef(kind="basic", name="String")
    if value is None:
        return TypeRef(kind="void")
    return TypeRef(kind="unknown")


def _infer_if_call_type(node: CallNode, arg_types: list[TypeRef | None]) -> TypeRef | None:
    if len(node.args) != 3:
        raise ValueError("if call must contain exactly three arguments")
    condition_type, then_type, else_type = arg_types
    if condition_type is not None and condition_type != TypeRef(kind="basic", name="boolean"):
        raise ValueError("if condition must be basic.boolean")
    if then_type is None or else_type is None:
        return None
    if then_type != else_type:
        raise ValueError(f"if branch type mismatch: {then_type} != {else_type}")
    return then_type


def _infer_list_search_call_type(node: CallNode, state: _ValidationState) -> TypeRef | None:
    if len(node.args) != 2:
        raise ValueError(f"{node.name} call must contain exactly two arguments")
    list_type = _validate_node(node.args[0], state)
    if list_type is None:
        return None
    if list_type.kind != "list" or list_type.element_type is None:
        raise ValueError(f"{node.name} first argument must be List<T>")
    predicate_state = _ValidationState(
        context=state.context,
        variable_types={**state.variable_types, "it": list_type.element_type},
    )
    predicate_type = _validate_node(node.args[1], predicate_state)
    boolean = TypeRef(kind="basic", name="boolean")
    if predicate_type != boolean:
        raise ValueError(f"{node.name} predicate must be basic.boolean")
    if state.context is None:
        return None
    matched = state.context.function_type_registry.match(
        node.name, [list_type, predicate_type]
    )
    if matched is None:
        raise ValueError(f"function signature not found: {node.name}")
    return matched


def _infer_context_path_type(path: str, state: _ValidationState) -> TypeRef | None:
    if not _is_registry_context_path(path) or state.context is None:
        return None

    root_path, root_type, remainder = _resolve_context_root(path, state)
    if root_path is None:
        raise ValueError(f"context path not found: {path}")
    current_type = root_type
    for field_name in remainder:
        current_type = _resolve_field_type(current_type, field_name, state)
    return current_type


def _resolve_context_root(path: str, state: _ValidationState) -> tuple[str | None, TypeRef | None, list[str]]:
    assert state.context is not None
    parts = [part for part in path.split(".") if part]
    for end in range(len(parts), 1, -1):
        candidate = ".".join(parts[:end])
        typed_root = state.context.context_types.get(candidate)
        if typed_root is not None:
            return candidate, typed_root, parts[end:]
        resource = state.context.context_registry.get(candidate)
        if resource is None:
            continue
        return_type = normalize_return_type(getattr(resource, "return_type", None))
        if return_type.kind == "unknown":
            return candidate, None, parts[end:]
        return candidate, return_type, parts[end:]
    return None, None, []


def _resolve_field_type(
    owner_type: TypeRef | None,
    field_name: str,
    state: _ValidationState,
) -> TypeRef | None:
    if owner_type is None or state.context is None or state.context.type_registry is None:
        return None
    if owner_type.kind == "list":
        raise ValueError(f"field access on list requires element method before field: {field_name}")
    if owner_type.kind == "basic":
        raise ValueError(f"field access on basic type {owner_type.kind}.{owner_type.name}: {field_name}")
    field_type = state.context.type_registry.resolve_field(owner_type, field_name)
    if field_type is None:
        raise ValueError(f"field not found on {owner_type.kind}.{owner_type.name}: {field_name}")
    return field_type


def _resolve_method_type(
    owner_type: TypeRef | None,
    method_name: str,
    arg_types: list[TypeRef | None],
    state: _ValidationState,
) -> TypeRef | None:
    if owner_type is None or state.context is None or state.context.method_registry is None:
        return None
    if any(arg_type is None for arg_type in arg_types):
        return None
    matched = state.context.method_registry.match(
        owner_type,
        method_name,
        [arg_type for arg_type in arg_types if arg_type is not None],
    )
    if matched is None:
        raise ValueError(f"method not found on {owner_type.kind}.{owner_type.name}: {method_name}")
    return matched


def _is_registry_context_path(path: str) -> bool:
    return path.startswith(("$ctx$.", "$local$.", "$iter$."))


def _validate_fetch_params(params) -> None:
    seen: set[str] = set()
    for param in params:
        if param.name in seen:
            raise ValueError(f"duplicate fetch param: {param.name}")
        seen.add(param.name)
