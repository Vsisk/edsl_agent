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
from agent.naming_sql_selector.models import NamingSqlSelectResponse
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
    max_items: int = Field(default=80, ge=1)


TypedExpressionContextBuildInput.model_rebuild(
    _types_namespace={"NamingSqlSelectResponse": NamingSqlSelectResponse}
)


class TypedExpressionContextBuilder:
    def build(self, build_input: TypedExpressionContextBuildInput) -> TypedExpressionContext:
        self._input = build_input
        self._warnings: list[str] = []
        self._method_catalog: dict[str, list[str]] = {}
        self._field_annotations: dict[tuple[tuple[Any, ...], str], str] = {}
        self._register_loaded_type_defs()
        self._register_selected_bos()
        self._register_candidate_return_types()

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
        return self._apply_item_budget(context)

    def _register_loaded_type_defs(self) -> None:
        for type_def in getattr(self._input.loaded_resource, "type_defs", []) or []:
            self._input.type_registry.register_type(type_def)

    def _register_selected_bos(self) -> None:
        bos: dict[str, BoRegistry] = {
            bo.bo_name: self._resolve_bo(bo.bo_name) or bo
            for bo in self._input.filtered_env.selected_bos
        }
        selection = self._input.filtered_env.naming_sql_selection
        if selection is not None:
            for candidate in selection.candidates:
                bo = self._resolve_bo(candidate.bo_name)
                if bo is not None:
                    bos[bo.bo_name] = bo
        for bo in bos.values():
            owner_type = TypeRef(kind="bo", name=bo.bo_name)
            fields = self._register_bo_type(bo)
            visited = {type_identity(owner_type)}
            for field_type in fields.values():
                self._register_reachable_type(field_type, visited)

    def _register_candidate_return_types(self) -> None:
        resources = [
            *self._input.filtered_env.selected_global_contexts,
            *self._input.filtered_env.visible_local_context,
        ]
        for resource in resources:
            authoritative = self._resolve_context(resource.context_name) or resource
            self._register_reachable_type(
                normalize_return_type(getattr(authoritative, "return_type", None)),
                set(),
            )
        for resource in self._input.filtered_env.selected_functions:
            authoritative = self._resolve_function(resource) or resource
            self._register_reachable_type(
                normalize_return_type(getattr(authoritative, "return_type", None)),
                set(),
            )

    def _register_reachable_type(
        self,
        type_ref: TypeRef,
        visited: set[tuple[Any, ...]],
    ) -> None:
        if type_ref.kind == "list" and type_ref.element_type is not None:
            self._register_reachable_type(type_ref.element_type, visited)
            return
        if type_ref.kind == "map":
            if type_ref.key_type is not None:
                self._register_reachable_type(type_ref.key_type, visited)
            if type_ref.value_type is not None:
                self._register_reachable_type(type_ref.value_type, visited)
            return
        if type_ref.kind not in {"bo", "logic", "extattr"}:
            return
        key = type_identity(type_ref)
        if key in visited:
            return
        visited.add(key)

        if type_ref.kind == "bo":
            bo = self._resolve_bo(type_ref.name or "")
            if bo is None:
                warning = f"missing type definition for {render_type(type_ref)}"
                if warning not in self._warnings:
                    self._warnings.append(warning)
                return
            fields = self._register_bo_type(bo)
        else:
            fields = self._input.type_registry.resolve_fields(type_ref)
        for field_type in fields.values():
            self._register_reachable_type(field_type, visited)

    def _register_bo_type(self, bo: BoRegistry) -> dict[str, TypeRef]:
        owner_type = TypeRef(kind="bo", name=bo.bo_name)
        fields = {
            prop.field_name: normalize_return_type(prop)
            for prop in bo.property_list
        }
        fields = {
            name: type_ref
            for name, type_ref in fields.items()
            if type_ref.kind != "unknown"
        }
        for prop in bo.property_list:
            self._field_annotations[(type_identity(owner_type), prop.field_name)] = (
                prop.description or ""
            )
        self._input.type_registry.register_type(
            TypeDef(owner_type=owner_type, fields=fields)
        )
        return fields

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
        if selection is None:
            return []
        templates: list[TypedVarTemplate] = []
        for candidate in selection.candidates:
            bo = self._resolve_bo(candidate.bo_name)
            type_ref = normalize_return_type(candidate.return_type)
            if bo is None or type_ref.kind == "unknown":
                self._warnings.append(
                    f"missing return_type for naming_sql {candidate.naming_sql_id}"
                )
                continue
            definition_name = candidate.naming_sql_name or candidate.naming_sql_id
            definition_expr = self._naming_sql_definition(candidate, bo, definition_name)
            templates.append(
                TypedVarTemplate(
                    var_name="it",
                    definition_expr=definition_expr,
                    return_type=render_type(type_ref),
                    available_fields=self._expand_fields("it", type_ref, set()),
                )
            )
        return templates

    def _naming_sql_definition(
        self,
        candidate: Any,
        bo: BoRegistry,
        definition_name: str,
    ) -> str:
        pairs: list[str] = []
        bo_fields = {
            _normalized_name(prop.field_name): prop.field_name
            for prop in bo.property_list
        }
        context_paths = [
            resource.context_name
            for resource in [
                *self._input.filtered_env.selected_global_contexts,
                *self._input.filtered_env.visible_local_context,
            ]
        ]
        contexts_by_name = {
            _normalized_name(path.rsplit(".", 1)[-1]): path
            for path in context_paths
        }
        for parameter in candidate.param_list:
            if not isinstance(parameter, dict):
                continue
            param_name = str(parameter.get("param_name") or parameter.get("name") or "")
            normalized = _normalized_name(param_name)
            bo_field = bo_fields.get(normalized)
            if bo_field is None:
                self._warnings.append(
                    f"unbound naming_sql BO field {candidate.naming_sql_id}.{param_name}"
                )
                continue
            context_path = contexts_by_name.get(normalized)
            if context_path is None:
                self._warnings.append(
                    f"unbound naming_sql context {candidate.naming_sql_id}.{param_name}"
                )
                continue
            pairs.append(f"pair(it.{bo_field}, {context_path})")
        if not pairs:
            return f"fetch_one({definition_name})"
        return f"fetch_one({definition_name}, {', '.join(pairs)})"

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

    def _apply_item_budget(self, context: TypedExpressionContext) -> TypedExpressionContext:
        remaining = self._input.max_items
        roots: list[TypedRootValue] = []
        for root in context.root_values:
            if remaining <= 0:
                break
            remaining -= 1
            field_count = min(len(root.fields), remaining)
            roots.append(root.model_copy(update={"fields": root.fields[:field_count]}))
            remaining -= field_count

        templates: list[TypedVarTemplate] = []
        for template in context.var_templates:
            if remaining <= 0:
                break
            remaining -= 1
            field_count = min(len(template.available_fields), remaining)
            templates.append(
                template.model_copy(
                    update={"available_fields": template.available_fields[:field_count]}
                )
            )
            remaining -= field_count

        emitted_types = {
            item.return_type
            for root in roots
            for item in [root, *root.fields]
        }
        emitted_types.update(
            item.return_type
            for template in templates
            for item in [template, *template.available_fields]
        )
        catalog: list[TypedMethodView] = []
        for method_view in context.method_catalog:
            if remaining <= 0:
                break
            if method_view.owner_type not in emitted_types:
                continue
            catalog.append(method_view)
            remaining -= 1

        patterns = context.expression_patterns[:remaining]
        return TypedExpressionContext(
            root_values=roots,
            var_templates=templates,
            method_catalog=catalog,
            expression_patterns=patterns,
            warnings=context.warnings,
        )


def render_type(type_ref: TypeRef) -> str:
    if type_ref.kind in {"basic", "bo", "logic", "extattr"}:
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


def _normalized_name(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())
