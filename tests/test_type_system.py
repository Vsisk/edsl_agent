import pytest

from agent.expression_generation.type_system import TypeRef, normalize_return_type
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

