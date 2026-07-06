from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class TypeRef(BaseModel):
    kind: Literal[
        "basic",
        "bo",
        "logic",
        "extattr",
        "list",
        "map",
        "void",
        "unknown",
    ]
    name: str | None = None
    element_type: "TypeRef | None" = None
    key_type: "TypeRef | None" = None
    value_type: "TypeRef | None" = None
    nullable: bool = True


TypeRef.model_rebuild()


class TypeDef(BaseModel):
    owner_type: TypeRef
    fields: dict[str, TypeRef]


class TypeRegistry:
    def __init__(self) -> None:
        self._types: dict[tuple[Any, ...], TypeDef] = {}

    def register_type(self, type_def: TypeDef) -> None:
        self._types[_type_key(type_def.owner_type)] = type_def

    def resolve_field(self, owner_type: TypeRef, field_name: str) -> TypeRef | None:
        type_def = self._types.get(_type_key(owner_type))
        if type_def is None:
            return None
        return type_def.fields.get(field_name)


class TypePattern(BaseModel):
    kind: Literal[
        "basic",
        "bo",
        "logic",
        "extattr",
        "list",
        "map",
        "void",
        "unknown",
        "var",
    ]
    name: str | None = None
    element_type: "TypePattern | None" = None
    key_type: "TypePattern | None" = None
    value_type: "TypePattern | None" = None
    nullable: bool = True


TypePattern.model_rebuild()


class MethodSig(BaseModel):
    owner_type: TypePattern
    name: str
    arg_types: list[TypePattern]
    return_type: TypePattern


class MethodRegistry:
    def __init__(self) -> None:
        self._methods: list[MethodSig] = []

    def register_method(self, method_sig: MethodSig) -> None:
        self._methods.append(method_sig)

    def match(
        self,
        owner_type: TypeRef,
        method_name: str,
        arg_types: list[TypeRef],
    ) -> TypeRef | None:
        for method in self._methods:
            if method.name != method_name or len(method.arg_types) != len(arg_types):
                continue
            bindings: dict[str, TypeRef] = {}
            if not _match_pattern(method.owner_type, owner_type, bindings):
                continue
            if not all(
                _match_pattern(pattern, actual, bindings)
                for pattern, actual in zip(method.arg_types, arg_types)
            ):
                continue
            return _resolve_pattern(method.return_type, bindings)
        return None


def create_builtin_method_registry() -> MethodRegistry:
    registry = MethodRegistry()
    register_builtin_methods(registry)
    return registry


def register_builtin_methods(registry: MethodRegistry) -> None:
    string = _named_pattern("basic", "String")
    date = _named_pattern("basic", "Date")
    integer = _named_pattern("basic", "int")
    long = _named_pattern("basic", "long")
    type_var = TypePattern(kind="var", name="T")
    list_of_t = TypePattern(kind="list", element_type=type_var)
    map_of_string_to_t = TypePattern(
        kind="map",
        key_type=string,
        value_type=type_var,
    )

    signatures = [
        MethodSig(owner_type=string, name="length", arg_types=[], return_type=integer),
        MethodSig(
            owner_type=string,
            name="substr",
            arg_types=[integer, integer],
            return_type=string,
        ),
        MethodSig(
            owner_type=string,
            name="dateValue",
            arg_types=[string],
            return_type=date,
        ),
        MethodSig(
            owner_type=string,
            name="replace",
            arg_types=[string, string],
            return_type=string,
        ),
        MethodSig(
            owner_type=date,
            name="addDays",
            arg_types=[integer],
            return_type=date,
        ),
        MethodSig(
            owner_type=date,
            name="toString",
            arg_types=[string],
            return_type=string,
        ),
        MethodSig(owner_type=integer, name="int2str", arg_types=[], return_type=string),
        MethodSig(owner_type=long, name="long2str", arg_types=[], return_type=string),
        MethodSig(owner_type=list_of_t, name="first", arg_types=[], return_type=type_var),
        MethodSig(owner_type=list_of_t, name="size", arg_types=[], return_type=integer),
        MethodSig(
            owner_type=list_of_t,
            name="find{expr}",
            arg_types=[],
            return_type=type_var,
        ),
        MethodSig(
            owner_type=list_of_t,
            name="findAll{expr}",
            arg_types=[],
            return_type=list_of_t,
        ),
        MethodSig(
            owner_type=map_of_string_to_t,
            name="get",
            arg_types=[string],
            return_type=type_var,
        ),
    ]
    for signature in signatures:
        registry.register_method(signature)


def normalize_return_type(raw_return_type: Any) -> TypeRef:
    if raw_return_type is None:
        return TypeRef(kind="unknown")

    data_type = _read_value(raw_return_type, "data_type")
    data_type_name = _read_value(raw_return_type, "data_type_name")
    is_list = _read_value(raw_return_type, "is_list")

    if isinstance(data_type, Enum):
        data_type = data_type.value
    if not isinstance(data_type, str):
        return TypeRef(kind="unknown")

    kind = data_type.strip().lower()
    name = data_type_name.strip() if isinstance(data_type_name, str) else None
    if kind == "void" or (name is not None and name.lower() == "void"):
        return TypeRef(kind="void")
    if kind not in {"basic", "bo", "logic", "extattr"} or not name:
        return TypeRef(kind="unknown")

    normalized = TypeRef(kind=kind, name=name)
    if is_list is True:
        return TypeRef(kind="list", element_type=normalized)
    return normalized


def _read_value(raw: Any, field_name: str) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(field_name)
    return getattr(raw, field_name, None)


def _type_key(type_ref: TypeRef | None) -> tuple[Any, ...] | None:
    if type_ref is None:
        return None
    return (
        type_ref.kind,
        type_ref.name,
        _type_key(type_ref.element_type),
        _type_key(type_ref.key_type),
        _type_key(type_ref.value_type),
        type_ref.nullable,
    )


def _named_pattern(kind: str, name: str) -> TypePattern:
    return TypePattern(kind=kind, name=name)


def _match_pattern(
    pattern: TypePattern,
    actual: TypeRef,
    bindings: dict[str, TypeRef],
) -> bool:
    if pattern.kind == "var":
        if not pattern.name:
            return False
        bound = bindings.get(pattern.name)
        if bound is None:
            bindings[pattern.name] = actual
            return True
        return bound == actual

    if (
        pattern.kind != actual.kind
        or pattern.name != actual.name
        or pattern.nullable != actual.nullable
    ):
        return False
    return (
        _match_optional_pattern(pattern.element_type, actual.element_type, bindings)
        and _match_optional_pattern(pattern.key_type, actual.key_type, bindings)
        and _match_optional_pattern(pattern.value_type, actual.value_type, bindings)
    )


def _match_optional_pattern(
    pattern: TypePattern | None,
    actual: TypeRef | None,
    bindings: dict[str, TypeRef],
) -> bool:
    if pattern is None or actual is None:
        return pattern is None and actual is None
    return _match_pattern(pattern, actual, bindings)


def _resolve_pattern(
    pattern: TypePattern,
    bindings: dict[str, TypeRef],
) -> TypeRef | None:
    if pattern.kind == "var":
        return bindings.get(pattern.name or "")

    element_type = _resolve_optional_pattern(pattern.element_type, bindings)
    key_type = _resolve_optional_pattern(pattern.key_type, bindings)
    value_type = _resolve_optional_pattern(pattern.value_type, bindings)
    if pattern.element_type is not None and element_type is None:
        return None
    if pattern.key_type is not None and key_type is None:
        return None
    if pattern.value_type is not None and value_type is None:
        return None
    return TypeRef(
        kind=pattern.kind,
        name=pattern.name,
        element_type=element_type,
        key_type=key_type,
        value_type=value_type,
        nullable=pattern.nullable,
    )


def _resolve_optional_pattern(
    pattern: TypePattern | None,
    bindings: dict[str, TypeRef],
) -> TypeRef | None:
    if pattern is None:
        return None
    return _resolve_pattern(pattern, bindings)
