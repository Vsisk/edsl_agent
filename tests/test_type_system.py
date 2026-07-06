import pytest

from agent.expression_generation.type_system import (
    MethodRegistry,
    MethodSig,
    TypeDef,
    TypePattern,
    TypeRef,
    TypeRegistry,
    create_builtin_method_registry,
    normalize_return_type,
)
from agent.resource_manager.loader.registry_models import ReturnType


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"data_type": "basic", "data_type_name": "String", "is_list": False},
            TypeRef(kind="basic", name="String"),
        ),
        (
            {"data_type": "basic", "data_type_name": "int", "is_list": False},
            TypeRef(kind="basic", name="int"),
        ),
        (
            {"data_type": "bo", "data_type_name": "BB_BILL_CHARGE", "is_list": False},
            TypeRef(kind="bo", name="BB_BILL_CHARGE"),
        ),
        (
            {"data_type": "bo", "data_type_name": "BB_BILL_CHARGE", "is_list": True},
            TypeRef(
                kind="list",
                element_type=TypeRef(kind="bo", name="BB_BILL_CHARGE"),
            ),
        ),
        (
            {"data_type": "logic", "data_type_name": "Address", "is_list": False},
            TypeRef(kind="logic", name="Address"),
        ),
        (
            {"data_type": "extattr", "data_type_name": "EXT_ATTR", "is_list": False},
            TypeRef(kind="extattr", name="EXT_ATTR"),
        ),
    ],
)
def test_normalize_return_type(raw, expected):
    assert normalize_return_type(raw) == expected


def test_normalize_return_type_accepts_existing_resource_model():
    raw = ReturnType(data_type="basic", data_type_name="String", is_list=False)

    assert normalize_return_type(raw) == TypeRef(kind="basic", name="String")


def test_normalize_return_type_returns_unknown_for_missing_metadata():
    assert normalize_return_type(None) == TypeRef(kind="unknown")


def test_type_registry_resolves_registered_bo_field():
    owner_type = TypeRef(kind="bo", name="BB_BILL_CHARGE")
    charge_amount_type = TypeRef(kind="basic", name="decimal")
    registry = TypeRegistry()
    registry.register_type(
        TypeDef(
            owner_type=owner_type,
            fields={"CHARGE_AMT": charge_amount_type},
        )
    )

    assert registry.resolve_field(owner_type, "CHARGE_AMT") == charge_amount_type
    assert registry.resolve_field(owner_type, "MISSING") is None


STRING = TypeRef(kind="basic", name="String")
DATE = TypeRef(kind="basic", name="Date")
INT = TypeRef(kind="basic", name="int")
LONG = TypeRef(kind="basic", name="long")
CHARGE = TypeRef(kind="bo", name="BB_BILL_CHARGE")


def list_of(element_type: TypeRef) -> TypeRef:
    return TypeRef(kind="list", element_type=element_type)


def map_of(key_type: TypeRef, value_type: TypeRef) -> TypeRef:
    return TypeRef(kind="map", key_type=key_type, value_type=value_type)


def test_method_registry_registers_and_matches_basic_signature():
    registry = MethodRegistry()
    registry.register_method(
        MethodSig(
            owner_type=TypePattern(kind="basic", name="String"),
            name="length",
            arg_types=[],
            return_type=TypePattern(kind="basic", name="int"),
        )
    )

    assert registry.match(STRING, "length", []) == INT


@pytest.mark.parametrize(
    ("owner", "method_name", "arg_types", "expected"),
    [
        (STRING, "length", [], INT),
        (STRING, "substr", [INT, INT], STRING),
        (STRING, "dateValue", [STRING], DATE),
        (STRING, "replace", [STRING, STRING], STRING),
        (DATE, "addDays", [INT], DATE),
        (DATE, "toString", [STRING], STRING),
        (INT, "int2str", [], STRING),
        (LONG, "long2str", [], STRING),
        (list_of(CHARGE), "first", [], CHARGE),
        (list_of(CHARGE), "size", [], INT),
        (list_of(CHARGE), "find{expr}", [], CHARGE),
        (list_of(CHARGE), "findAll{expr}", [], list_of(CHARGE)),
        (map_of(STRING, CHARGE), "get", [STRING], CHARGE),
    ],
)
def test_builtin_method_registry_matches_signatures(
    owner, method_name, arg_types, expected
):
    registry = create_builtin_method_registry()

    assert registry.match(owner, method_name, arg_types) == expected


def test_method_registry_returns_none_for_non_matching_signature():
    registry = create_builtin_method_registry()

    assert registry.match(STRING, "dateValue", [INT]) is None
    assert registry.match(STRING, "missing", []) is None
