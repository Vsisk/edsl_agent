from __future__ import annotations

from enum import Enum
from typing import Any

from agent.context_manager.models import ContextAsset
from agent.resource_manager.models import (
    BoRegistry,
    ContextRegistry,
    FunctionRegistry,
    LocalContextRegistry,
    NamingSqlDefTerm,
    PropertyTerm,
)


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return "" if value is None else str(value)


def _labeled(**parts: Any) -> str:
    return "; ".join(f"{label}: {_value(value)}" for label, value in parts.items() if value not in (None, "", []))


class ResourceAssetBuilder:
    """Pure conversion from authoritative resource registries to semantic assets."""

    source = "resource_registry"

    def bo(self, registry: BoRegistry) -> ContextAsset:
        fields = ", ".join(
            _labeled(name=item.field_name, description=item.description, type=item.data_type_name, list=item.is_list)
            for item in registry.property_list
        )
        return ContextAsset(
            asset_id=f"bo:{registry.bo_name}", asset_type="bo", scope="global",
            content=registry.model_dump(mode="json"),
            index_text=_labeled(resource="business object", name=registry.bo_name, description=registry.bo_desc, fields=fields),
            source=self.source,
        )

    def bo_field(self, bo_name: str, field: PropertyTerm) -> ContextAsset:
        return ContextAsset(
            asset_id=f"bo_field:{bo_name}:{field.field_name}", asset_type="bo_field", scope="global",
            content={"bo_name": bo_name, **field.model_dump(mode="json")},
            index_text=_labeled(resource="business object field", bo=bo_name, name=field.field_name, description=field.description, type=field.data_type_name, data_category=field.data_type, list=field.is_list),
            source=self.source,
        )

    def naming_sql(self, bo_name: str, definition: NamingSqlDefTerm) -> ContextAsset:
        params = ", ".join(
            _labeled(name=item.param_name, type=item.data_type_name, data_category=item.data_type, list=item.is_list)
            for item in definition.param_list
        )
        return ContextAsset(
            asset_id=f"naming_sql:{bo_name}:{definition.naming_sql_id}", asset_type="naming_sql", scope="global",
            content={"bo_name": bo_name, **definition.model_dump(mode="json")},
            index_text=_labeled(resource="NamingSQL", bo=bo_name, id=definition.naming_sql_id, name=definition.sql_name, purpose=definition.sql_description, label=definition.label_name, parameters=params),
            source=self.source,
        )

    def context(self, registry: ContextRegistry | LocalContextRegistry) -> ContextAsset:
        property_type = _value(registry.property_type).lower()
        path = registry.context_name
        is_iter = property_type == "iter" or path.startswith(("$iter$", "it."))
        if is_iter:
            asset_type, scope = "iter_context", "node"
        elif isinstance(registry, LocalContextRegistry) or property_type == "local" or path.startswith("$local$"):
            asset_type, scope = "local_context", "node"
        else:
            asset_type, scope = "global_context", "global"
        return_type = registry.return_type
        return ContextAsset(
            asset_id=f"context:{registry.resource_id}", asset_type=asset_type, scope=scope,
            content=registry.model_dump(mode="json"),
            index_text=_labeled(resource=asset_type.replace("_", " "), path=path, annotation=registry.annotation, return_type=getattr(return_type, "data_type", None), return_type_name=getattr(return_type, "data_type_name", None), list=getattr(return_type, "is_list", None), source_path=getattr(registry, "source_path", None)),
            source=self.source,
        )

    def function(self, registry: FunctionRegistry) -> ContextAsset:
        params = ", ".join(
            _labeled(name=item.param_name, type=item.data_type_name, data_category=item.data_type, list=item.is_list)
            for item in registry.param_list
        )
        function_id = f"function:{registry.func_class}:{registry.func_name}" if registry.func_class else f"function:{registry.func_name}"
        return ContextAsset(
            asset_id=function_id, asset_type="function", scope="global",
            content=registry.model_dump(mode="json"),
            index_text=_labeled(resource="function", class_name=registry.func_class, name=registry.func_name, description=registry.func_desc, parameters=params, return_type=registry.return_type.data_type_name, return_category=registry.return_type.data_type, return_list=registry.return_type.is_list),
            source=self.source,
        )
