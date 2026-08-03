from __future__ import annotations

from collections.abc import Iterable

from agent.expression_generation.type_system import TypeDef, TypeRef


EXPANDABLE_TYPE_KINDS = {"bo", "logic", "extattr"}


class StructuredTypeExpander:
    def __init__(self, type_defs: Iterable[TypeDef]) -> None:
        self._fields = {
            self._type_key(type_def.owner_type): dict(type_def.fields)
            for type_def in type_defs
        }

    def descendants(self, root_type: TypeRef) -> list[tuple[str, TypeRef]]:
        return list(self._walk(root_type, active_types=frozenset()))

    def _walk(
        self,
        owner_type: TypeRef,
        *,
        active_types: frozenset[tuple[str, str]],
    ):
        normalized_owner = self._unwrap_list(owner_type)
        owner_key = self._type_key(normalized_owner)
        if owner_key is None or owner_key in active_types:
            return

        fields = self._fields.get(owner_key)
        if not fields:
            return

        next_active = active_types | {owner_key}
        for field_name, field_type in fields.items():
            yield field_name, field_type
            for child_path, child_type in self._walk(field_type, active_types=next_active):
                yield f"{field_name}.{child_path}", child_type

    @staticmethod
    def _unwrap_list(type_ref: TypeRef) -> TypeRef:
        if type_ref.kind == "list" and type_ref.element_type is not None:
            return type_ref.element_type
        return type_ref

    @staticmethod
    def _type_key(type_ref: TypeRef) -> tuple[str, str] | None:
        if type_ref.kind not in EXPANDABLE_TYPE_KINDS or not type_ref.name:
            return None
        return type_ref.kind, type_ref.name
