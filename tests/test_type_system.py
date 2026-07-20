import pytest

from agent.expression_generation.type_system import (
    FunctionSig,
    FunctionTypeRegistry,
    MethodRegistry,
    MethodSig,
    TypeDef,
    TypePattern,
    TypeRef,
    TypeRegistry,
    create_builtin_method_registry,
    create_builtin_function_type_registry,
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


@pytest.mark.parametrize(
    ("function_name", "expected"),
    [
        ("find", CHARGE),
        ("find_all", list_of(CHARGE)),
    ],
)
def test_builtin_function_registry_resolves_generic_list_return_type(
    function_name, expected
):
    registry = create_builtin_function_type_registry()

    assert registry.match(
        function_name,
        [list_of(CHARGE), TypeRef(kind="basic", name="boolean")],
    ) == expected


def test_function_registry_supports_custom_registration():
    registry = FunctionTypeRegistry()
    registry.register_function(
        FunctionSig(
            name="identity",
            arg_types=[TypePattern(kind="var", name="T")],
            return_type=TypePattern(kind="var", name="T"),
        )
    )

    assert registry.match("identity", [STRING]) == STRING


def test_builtin_function_registry_matches_existing_and_variadic_functions():
    registry = create_builtin_function_type_registry()

    assert registry.match("exists", [STRING]) == TypeRef(kind="basic", name="boolean")
    assert registry.match(
        "if", [TypeRef(kind="basic", name="boolean"), STRING, STRING]
    ) == STRING
    assert registry.match("join", [STRING, STRING, STRING]) == STRING
    assert registry.match("join", [STRING, INT]) is None
    assert {"if", "exists", "join", "find", "find_all"} <= registry.function_names()


def test_method_registry_returns_none_for_non_matching_signature():
    registry = create_builtin_method_registry()

    assert registry.match(STRING, "dateValue", [INT]) is None
    assert registry.match(STRING, "missing", []) is None


def test_type_registry_lists_registered_fields_without_exposing_internal_mapping():
    owner = TypeRef(kind="bo", name="BB_BILL_CHARGE")
    registry = TypeRegistry()
    registry.register_type(TypeDef(owner_type=owner, fields={"CHARGE_AMT": LONG}))

    fields = registry.resolve_fields(owner)
    fields["OTHER"] = STRING

    assert fields == {"CHARGE_AMT": LONG, "OTHER": STRING}
    assert registry.resolve_fields(owner) == {"CHARGE_AMT": LONG}


def test_type_registry_preserves_registered_field_description():
    owner = TypeRef(kind="bo", name="BB_BILL_CHARGE")
    registry = TypeRegistry()
    registry.register_type(
        TypeDef(
            owner_type=owner,
            fields={"CHARGE_AMT": LONG},
            field_descriptions={"CHARGE_AMT": "charge amount"},
        )
    )

    assert registry.resolve_field_description(owner, "CHARGE_AMT") == "charge amount"


def test_method_registry_lists_only_methods_for_concrete_owner():
    registry = create_builtin_method_registry()

    list_methods = registry.methods_for(list_of(CHARGE))
    string_methods = registry.methods_for(STRING)

    assert [method.name for method in list_methods] == [
        "first",
        "size",
        "find{expr}",
        "findAll{expr}",
    ]
    assert list_methods[0].return_type == CHARGE
    assert [method.name for method in string_methods] == [
        "length",
        "substr",
        "dateValue",
        "replace",
    ]
    assert string_methods[1].arg_names == ["start", "length"]


def test_normalize_return_type_preserves_already_normalized_type_ref():
    normalized = map_of(STRING, CHARGE)

    assert normalize_return_type(normalized) == normalized
