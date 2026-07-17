from __future__ import annotations

from typing import Any, Dict, Iterable, Literal

from agent.expression_generation.type_system import TypeDef, TypeRef, normalize_return_type


StructuredKind = Literal["logic", "extattr"]


def load_structured_type_defs_from_json(payload: Dict[str, Any]) -> list[TypeDef]:
    type_defs: list[TypeDef] = []
    type_defs.extend(load_logic_type_defs_by_json(payload.get("logic") or payload))
    type_defs.extend(load_extattr_type_defs_by_json(payload.get("extattr") or payload))
    return _dedupe_type_defs(type_defs)


def load_logic_type_defs_by_json(payload: Dict[str, Any]) -> list[TypeDef]:
    return _load_type_defs(payload.get("logic_list") or [], "logic")


def load_extattr_type_defs_by_json(payload: Dict[str, Any]) -> list[TypeDef]:
    return _load_type_defs(payload.get("extattr_list") or [], "extattr")


def _load_type_defs(items: Iterable[Any], kind: StructuredKind) -> list[TypeDef]:
    type_defs: list[TypeDef] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        type_name = str(item.get("type_name") or "").strip()
        if not type_name:
            continue
        fields, field_descriptions = _collect_fields(
            item.get("sub_properties") or []
        )
        type_defs.append(
            TypeDef(
                owner_type=TypeRef(kind=kind, name=type_name),
                fields=fields,
                field_descriptions=field_descriptions,
            )
        )
    return type_defs


def _collect_fields(
    items: Iterable[Any],
) -> tuple[dict[str, TypeRef], dict[str, str]]:
    fields: dict[str, TypeRef] = {}
    field_descriptions: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("property_name") or "").strip()
        if not field_name:
            continue
        type_ref = normalize_return_type(item.get("data_type"))
        if type_ref.kind == "unknown":
            continue
        fields[field_name] = type_ref
        description = str(
            item.get("property_annotation")
            or item.get("annotation")
            or item.get("description")
            or ""
        ).strip()
        if description:
            field_descriptions[field_name] = description
    return fields, field_descriptions


def _dedupe_type_defs(type_defs: list[TypeDef]) -> list[TypeDef]:
    result: list[TypeDef] = []
    seen: set[tuple[str, str | None]] = set()
    for type_def in type_defs:
        key = (type_def.owner_type.kind, type_def.owner_type.name)
        if key in seen:
            continue
        seen.add(key)
        result.append(type_def)
    return result
