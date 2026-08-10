from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SkipValidation

from agent.environment.environment import FilteredEnvironment
from agent.context_pack.models import ContextPack
from agent.expression_generation.type_system import (
    MethodRegistry,
    ResolvedMethod,
    TypeDef,
    TypeRef,
    TypeRegistry,
    normalize_return_type,
)
from agent.models import NodeDef
from agent.resource_manager.loader.registry_models import BoRegistry
from agent.resource_manager.loader.resource_loader import LoadedResource


class TypedAccessView(BaseModel):
    access: str
    return_type: str
    methods: list[str] = Field(default_factory=list)


class TypedRootValue(BaseModel):
    expr: str
    source_type: str
    return_type: str
    methods: list[str] = Field(default_factory=list)
    fields: list[TypedAccessView] = Field(default_factory=list)


class TypedVarTemplate(BaseModel):
    var_name: str
    definition_expr: str
    return_type: str
    available_fields: list[TypedAccessView] = Field(default_factory=list)


class TypedMethodView(BaseModel):
    owner_type: str
    methods: list[str] = Field(default_factory=list)


class TypedExpressionPattern(BaseModel):
    name: str
    expression: str


class TypedExpressionContext(BaseModel):
    root_values: list[TypedRootValue] = Field(default_factory=list)
    var_templates: list[TypedVarTemplate] = Field(default_factory=list)
    method_catalog: list[TypedMethodView] = Field(default_factory=list)
    expression_patterns: list[TypedExpressionPattern] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TypedExpressionContextBuildInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    query: str
    node: NodeDef
    filtered_env: SkipValidation[FilteredEnvironment]
    loaded_resource: SkipValidation[LoadedResource]
    context_pack: SkipValidation[ContextPack]
    type_registry: TypeRegistry
    method_registry: MethodRegistry
    max_items: int = Field(
        default=80,
        ge=1,
        description="Deprecated compatibility field; typed context is no longer truncated.",
    )


class TypedExpressionContextBuilder:
    def build(self, build_input: TypedExpressionContextBuildInput) -> TypedExpressionContext:
        self._input = build_input
        self._warnings: list[str] = []
        self._method_catalog: dict[str, list[str]] = {}
        self._field_annotations: dict[tuple[tuple[Any, ...], str], str] = {}
        self._register_loaded_type_defs()
        self._register_selected_bos()

        roots: list[TypedRootValue] = []
        for resource in build_input.filtered_env.selected_global_contexts:
            self._append_context_root(roots, resource, "context")
        for resource in build_input.filtered_env.visible_local_context:
            self._append_context_root(roots, resource, "local_context")
        for resource in build_input.filtered_env.selected_functions:
            self._append_function_root(roots, resource)

        var_templates = self._build_naming_sql_templates()
        context = TypedExpressionContext(
            root_values=roots,
            var_templates=var_templates,
            method_catalog=[
                TypedMethodView(owner_type=owner, methods=methods)
                for owner, methods in self._method_catalog.items()
            ],
            expression_patterns=self._build_patterns(var_templates),
            warnings=self._warnings,
        )
        return context

    def _register_loaded_type_defs(self) -> None:
        for type_def in getattr(self._input.loaded_resource, "type_defs", []) or []:
            self._input.type_registry.register_type(type_def)

    def _register_selected_bos(self) -> None:
        bos: dict[str, BoRegistry] = {
            bo.bo_name: self._resolve_bo(bo.bo_name) or bo
            for bo in self._input.filtered_env.selected_bos
        }
        for resource in self._input.filtered_env.visible_local_context:
            type_ref = normalize_return_type(getattr(resource, "return_type", None))
            bo_type = _bo_type(type_ref)
            if bo_type is None:
                continue
            bo = self._resolve_bo(bo_type.name or "")
            if bo is not None:
                bos[bo.bo_name] = bo
        selection = self._input.filtered_env.naming_sql_selection
        if selection:
            for profile in selection:
                bo = self._resolve_bo(profile.bo_name)
                if bo is not None:
                    bos[bo.bo_name] = bo
        for bo in bos.values():
            owner_type = TypeRef(kind="bo", name=bo.bo_name)
            fields = {
                prop.field_name: normalize_return_type(prop)
                for prop in bo.property_list
            }
            fields = {name: type_ref for name, type_ref in fields.items() if type_ref.kind != "unknown"}
            for prop in bo.property_list:
                self._field_annotations[(type_identity(owner_type), prop.field_name)] = (
                    prop.description or ""
                )
            self._input.type_registry.register_type(
                TypeDef(
                    owner_type=owner_type,
                    fields=fields,
                )
            )

    def _append_context_root(self, roots: list[TypedRootValue], resource: Any, source_type: str) -> None:
        authoritative = self._resolve_context(resource.context_name) or resource
        type_ref = normalize_return_type(getattr(authoritative, "return_type", None))
        if type_ref.kind == "unknown":
            self._warnings.append(f"missing return_type for context {resource.context_name}")
            return
        roots.append(self._root(resource.context_name, source_type, type_ref))

    def _append_function_root(self, roots: list[TypedRootValue], resource: Any) -> None:
        authoritative = self._resolve_function(resource) or resource
        type_ref = normalize_return_type(getattr(authoritative, "return_type", None))
        name = ".".join(
            part for part in (authoritative.func_class, authoritative.func_name) if part
        )
        if type_ref.kind == "unknown":
            self._warnings.append(f"missing return_type for function {name}")
            return
        roots.append(self._root(name, "function", type_ref))

    def _root(self, expr: str, source_type: str, type_ref: TypeRef) -> TypedRootValue:
        methods = self._methods(type_ref)
        return TypedRootValue(
            expr=expr,
            source_type=source_type,
            return_type=render_type(type_ref),
            methods=methods,
            fields=self._expand_fields(expr, type_ref, set()),
        )

    def _expand_fields(
        self,
        prefix: str,
        owner_type: TypeRef,
        path_types: set[tuple[Any, ...]],
    ) -> list[TypedAccessView]:
        if owner_type.kind == "list" and owner_type.element_type is not None:
            return self._expand_fields(f"{prefix}.first()", owner_type.element_type, path_types)
        if owner_type.kind == "map" and owner_type.value_type is not None:
            return self._expand_fields(f"{prefix}.get(...)" , owner_type.value_type, path_types)
        if owner_type.kind not in {"bo", "logic", "extattr"}:
            return []
        key = type_identity(owner_type)
        if key in path_types:
            warning = f"recursive type cycle at {prefix}: {render_type(owner_type)}"
            if warning not in self._warnings:
                self._warnings.append(warning)
            return []
        nested_path = {*path_types, key}
        result: list[TypedAccessView] = []
        fields = list(self._input.type_registry.resolve_fields(owner_type).items())
        fields.sort(
            key=lambda item: (
                -self._field_relevance(owner_type, item[0]),
                item[0],
            )
        )
        for field_name, field_type in fields:
            access = f"{prefix}.{field_name}"
            result.append(
                TypedAccessView(
                    access=access,
                    return_type=render_type(field_type),
                    methods=self._methods(field_type),
                )
            )
            result.extend(self._expand_fields(access, field_type, nested_path))
        return result

    def _field_relevance(self, owner_type: TypeRef, field_name: str) -> int:
        normalized = field_name.lower()
        query = self._input.query.lower()
        node_name = self._input.node.node_name.lower()
        annotation = self._field_annotations.get(
            (type_identity(owner_type), field_name), ""
        ).lower()
        annotation_matches = sum(
            1 for token in query.split() if token and token in annotation
        )
        return (
            (4 if normalized in query else 0)
            + (2 if normalized == node_name else 0)
            + annotation_matches
        )

    def _methods(self, owner_type: TypeRef) -> list[str]:
        signatures = [render_method(method) for method in self._input.method_registry.methods_for(owner_type)]
        if signatures:
            owner = render_type(owner_type)
            catalog = self._method_catalog.setdefault(owner, [])
            for signature in signatures:
                if signature not in catalog:
                    catalog.append(signature)
        return signatures

    def _build_naming_sql_templates(self) -> list[TypedVarTemplate]:
        selection = self._input.filtered_env.naming_sql_selection
        if not selection:
            return []
        templates: list[TypedVarTemplate] = []
        for profile in selection:
            bo = self._resolve_bo(profile.bo_name)
            if bo is None:
                self._warnings.append(f"missing BO for naming_sql {profile.namingsql_name}")
                continue
            type_ref = TypeRef(kind="bo", name=bo.bo_name)
            definition_name = profile.namingsql_name
            definition_expr = f"fetch_one({definition_name})"
            templates.append(
                TypedVarTemplate(
                    var_name="it",
                    definition_expr=definition_expr,
                    return_type=render_type(type_ref),
                    available_fields=[
                        TypedAccessView(
                            access=f"it.{field.field_name}",
                            return_type=render_type(normalize_return_type(field)),
                            methods=self._methods(normalize_return_type(field)),
                        )
                        for field in bo.property_list
                        if field.field_name in profile.return_fields
                    ],
                )
            )
        return templates

    def _build_patterns(
        self,
        templates: list[TypedVarTemplate],
    ) -> list[TypedExpressionPattern]:
        return [
            TypedExpressionPattern(
                name="naming_sql_fetch_one",
                expression=template.definition_expr,
            )
            for template in templates
        ]

    def _resolve_context(self, context_name: str) -> Any | None:
        return self._input.loaded_resource.context_registry.get(context_name)

    def _resolve_bo(self, bo_name: str) -> BoRegistry | None:
        return self._input.loaded_resource.bo_registry.get(bo_name)

    def _resolve_function(self, resource: Any) -> Any | None:
        for candidate in self._input.loaded_resource.function_registry.values():
            if (
                candidate.resource_id == resource.resource_id
                or (
                    candidate.func_class == resource.func_class
                    and candidate.func_name == resource.func_name
                )
            ):
                return candidate
        return None

def render_type(type_ref: TypeRef) -> str:
    if type_ref.kind in {"basic", "key", "bo", "logic", "extattr"}:
        return f"{type_ref.kind}.{type_ref.name}"
    if type_ref.kind == "list" and type_ref.element_type is not None:
        return f"List<{render_type(type_ref.element_type)}>"
    if type_ref.kind == "map" and type_ref.key_type is not None and type_ref.value_type is not None:
        return f"Map<{render_type(type_ref.key_type)},{render_type(type_ref.value_type)}>"
    return type_ref.kind


def render_method(method: ResolvedMethod) -> str:
    args = []
    for index, arg_type in enumerate(method.arg_types):
        name = method.arg_names[index] if index < len(method.arg_names) else f"arg{index + 1}"
        args.append(f"{render_type(arg_type)} {name}")
    return f"{method.name}({', '.join(args)}): {render_type(method.return_type)}"


def type_identity(type_ref: TypeRef) -> tuple[Any, ...]:
    return (
        type_ref.kind,
        type_ref.name,
        type_identity(type_ref.element_type) if type_ref.element_type else None,
        type_identity(type_ref.key_type) if type_ref.key_type else None,
        type_identity(type_ref.value_type) if type_ref.value_type else None,
    )


def _bo_type(type_ref: TypeRef) -> TypeRef | None:
    if type_ref.kind == "bo":
        return type_ref
    if (
        type_ref.kind == "list"
        and type_ref.element_type is not None
        and type_ref.element_type.kind == "bo"
    ):
        return type_ref.element_type
    return None


def _normalized_name(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())
