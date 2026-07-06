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

