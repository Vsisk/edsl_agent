from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.environment.environment import FilteredEnvironment, build_filtered_environment
from agent.llm.generate_by_llm import generate_by_llm
from agent.models import NodeDef, ValueLogicResult, ValueLogicSource, ValueReturnType
from agent.resource_manager.loader.namingsql_profile_loader import NamingSqlProfile, NamingSqlProfileLoader
from agent.resource_manager.loader.resource_loader import LoadedResource
from agent.resource_manager.loader.registry_models import BoRegistry


class SqlBoSelection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bo_keywords: list[str] = Field(default_factory=list)


class SqlParamBinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    param_name: str
    param_value: Any


class SqlParamBindingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sql_condition: list[SqlParamBinding] = Field(default_factory=list)

    def bindings(self) -> list[SqlParamBinding]:
        return self.sql_condition


class SqlBranchBoSelector:
    def __init__(self, decision_fn: Callable[..., Any] = generate_by_llm) -> None:
        self.decision_fn = decision_fn

    def select(
        self,
        *,
        query: str,
        node: dict[str, Any],
        bo_registry: dict[str, BoRegistry],
        context_pack: Any,
    ) -> str | None:
        if not bo_registry:
            return None
        bo_candidates_json = _dump_bo_candidates(bo_registry)
        try:
            raw = self.decision_fn(
                prompt_template="value_logic_sql_bo_selector",
                llm_name="base",
                lang="zh",
                query=str(query or "")[:4000],
                node_json=_dump(node),
                bo_candidates_json=bo_candidates_json,
                context_pack_json=_dump(_model_dump(context_pack)),
            )
            keywords = SqlBoSelection.model_validate(raw).bo_keywords
        except Exception:
            return None
        return _match_bo_name_by_keywords(keywords, bo_registry)


class SqlParamBinder:
    def __init__(self, decision_fn: Callable[..., Any] = generate_by_llm) -> None:
        self.decision_fn = decision_fn

    def bind(
        self,
        *,
        query: str,
        node: dict[str, Any],
        sql_name: str,
        params: list[Any],
        filtered_env: FilteredEnvironment,
    ) -> list[dict[str, Any]] | None:
        if not params:
            return []
        raw = self.decision_fn(
            prompt_template="value_logic_sql_param_binder",
            llm_name="base",
            lang="zh",
            query=str(query or "")[:4000],
            node_json=_dump(node),
            sql_name=sql_name,
            params_json=_dump(_param_summaries(params)),
            available_context_json=_dump(_available_context(filtered_env)),
        )
        try:
            response = SqlParamBindingResponse.model_validate(raw)
        except (ValidationError, TypeError, ValueError):
            return None
        return _normalize_param_bindings(response.bindings(), params, filtered_env)


class SqlBranchResolver:
    def __init__(
        self,
        *,
        bo_selector: Callable[..., str | None] | SqlBranchBoSelector,
        naming_sql_selector_factory: Callable[[], Any],
        param_binder: Callable[..., list[dict[str, Any]] | None] | SqlParamBinder,
        llm_resource_filter: Any | None = None,
    ) -> None:
        self.bo_selector = bo_selector
        self.naming_sql_selector_factory = naming_sql_selector_factory
        self.param_binder = param_binder
        self.llm_resource_filter = llm_resource_filter

    def resolve(
        self,
        *,
        query: str,
        node: dict[str, Any],
        loaded_resource: LoadedResource,
        node_path: str,
        context_pack: Any,
    ) -> ValueLogicResult | None:
        bo_registry = loaded_resource.bo_registry
        bo_name = self._select_bo(
            query=query,
            node=node,
            bo_registry=bo_registry,
            context_pack=context_pack,
        )
        if not bo_name:
            return None
        bo = bo_registry.get(bo_name)
        if bo is None or not bo.naming_sql_list:
            return None

        profiles = NamingSqlProfileLoader().load_bo(bo)
        selected_profiles = self.naming_sql_selector_factory().select(
            query=query,
            profiles=profiles,
            top_k=1,
        )
        if not selected_profiles:
            return None

        profile = selected_profiles[0]
        sql_def = _find_sql_definition(bo, profile)
        if sql_def is None:
            return None
        filtered_env = build_filtered_environment(
            NodeDef(
                node_id=_node_id(node) or "",
                node_path=node_path,
                node_name=_node_name(node),
                description=str(node.get("description") or node.get("annotation") or ""),
                is_ab=bool(node.get("is_ab")),
            ),
            _param_binding_query(query, sql_def),
            loaded_resource,
            top_global_context=5,
            top_local_context=5,
            top_bo=0,
            top_function=0,
            llm_resource_filter=self.llm_resource_filter,
        )
        _include_param_named_contexts(
            filtered_env,
            loaded_resource=loaded_resource,
            node_path=node_path,
            params=list(sql_def.param_list or []),
        )
        sql_params = self._bind_params(
            query=query,
            node=node,
            sql_def=sql_def,
            filtered_env=filtered_env,
        )
        if sql_params is None:
            return None
        return ValueLogicResult(
            node_id=_node_id(node),
            logic_type="sql",
            expression=profile.namingsql_name,
            return_type=ValueReturnType(is_list=True, data_type="bo", data_type_name=bo.bo_name),
            source=ValueLogicSource(
                source_type="sql",
                bo_name=bo.bo_name,
                sql_name=profile.namingsql_name,
                naming_sql_id=getattr(sql_def, "naming_sql_id", None),
                sql_params=sql_params,
            ),
        )

    def _select_bo(
        self,
        *,
        query: str,
        node: dict[str, Any],
        bo_registry: dict[str, BoRegistry],
        context_pack: Any,
    ) -> str | None:
        kwargs = {
            "query": query,
            "node": node,
            "bo_registry": bo_registry,
            "context_pack": context_pack,
        }
        if hasattr(self.bo_selector, "select"):
            selected = self.bo_selector.select(**kwargs)
        else:
            selected = self.bo_selector(
                **kwargs,
                bo_candidates_json=_dump_bo_candidates(bo_registry),
            )
        if selected in bo_registry:
            return selected
        return None

    def _bind_params(
        self,
        *,
        query: str,
        node: dict[str, Any],
        sql_def: Any,
        filtered_env: FilteredEnvironment,
    ) -> list[dict[str, Any]] | None:
        kwargs = {
            "query": query,
            "node": node,
            "sql_name": sql_def.sql_name,
            "params": list(sql_def.param_list or []),
            "filtered_env": filtered_env,
            "params_json": _dump(_param_summaries(sql_def.param_list or [])),
            "available_context_json": _dump(_available_context(filtered_env)),
        }
        if hasattr(self.param_binder, "bind"):
            raw_bindings = self.param_binder.bind(
                query=query,
                node=node,
                sql_name=sql_def.sql_name,
                params=list(sql_def.param_list or []),
                filtered_env=filtered_env,
            )
        else:
            raw_bindings = self.param_binder(**kwargs)
        if raw_bindings is None:
            return None
        try:
            bindings = [SqlParamBinding.model_validate(item) for item in raw_bindings]
        except (ValidationError, TypeError, ValueError):
            return None
        return _normalize_param_bindings(bindings, list(sql_def.param_list or []), filtered_env)


def _find_sql_definition(bo: BoRegistry, profile: NamingSqlProfile) -> Any | None:
    for definition in bo.naming_sql_list:
        if definition.sql_name == profile.namingsql_name:
            return definition
    return None


def _dump_bo_candidates(bo_registry: dict[str, BoRegistry]) -> str:
    candidates = [
        {
            "bo_name": bo.bo_name,
            "bo_desc": bo.bo_desc,
            "fields": [field.field_name for field in bo.property_list[:50]],
            "naming_sql_count": len(bo.naming_sql_list),
        }
        for bo in bo_registry.values()
    ]
    return _dump(candidates)


def _match_bo_name_by_keywords(
    keywords: list[str],
    bo_registry: dict[str, BoRegistry],
) -> str | None:
    normalized_keywords = [
        normalized
        for keyword in keywords
        if (normalized := _normalize_match_text(keyword))
    ]
    if not normalized_keywords:
        return None

    for bo_name in bo_registry:
        normalized_bo_name = _normalize_match_text(bo_name)
        if any(keyword in normalized_bo_name for keyword in normalized_keywords):
            return bo_name
    return None


def _normalize_match_text(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _normalize_param_bindings(
    bindings: list[SqlParamBinding],
    params: list[Any],
    filtered_env: FilteredEnvironment,
) -> list[dict[str, Any]] | None:
    required = [param.param_name for param in params]
    by_param = {binding.param_name: binding for binding in bindings}
    available_values = {
        item.context_name for item in [
            *filtered_env.selected_global_contexts,
            *filtered_env.visible_local_context,
        ]
    }
    result: list[dict[str, Any]] = []
    for param_name in required:
        binding = by_param.get(param_name)
        if binding is None:
            result.append(_default_param_binding(param_name))
            continue
        if binding.param_value is None:
            result.append(_default_param_binding(param_name))
            continue
        if _looks_like_context(binding.param_value) and binding.param_value not in available_values:
            result.append(_default_param_binding(param_name))
            continue
        result.append({"param_name": param_name, "param_value": binding.param_value})
    return result


def _default_param_binding(param_name: str) -> dict[str, Any]:
    return {"param_name": param_name, "param_value": ""}


def _looks_like_context(value: Any) -> bool:
    text = str(value or "")
    return text.startswith("$ctx$.") or text.startswith("$local$.") or text.startswith("$iter$.")


def _param_binding_query(query: str, sql_def: Any) -> str:
    param_names = " ".join(param.param_name for param in sql_def.param_list or [])
    return " ".join(part for part in (query, sql_def.sql_name, param_names) if part)


def _param_summaries(params: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "param_name": param.param_name,
            "data_type": getattr(param, "data_type", None),
            "data_type_name": param.data_type_name,
            "is_list": param.is_list,
        }
        for param in params
    ]


def _available_context(filtered_env: FilteredEnvironment) -> dict[str, list[dict[str, Any]]]:
    return {
        "global_context": [
            {
                "context_name": item.context_name,
                "annotation": item.annotation,
                "return_type": _model_dump(item.return_type),
            }
            for item in filtered_env.selected_global_contexts
        ],
        "local_context": [
            {
                "context_name": item.context_name,
                "annotation": item.annotation,
                "return_type": _model_dump(item.return_type),
            }
            for item in filtered_env.visible_local_context
        ],
    }


def _include_param_named_contexts(
    filtered_env: FilteredEnvironment,
    *,
    loaded_resource: LoadedResource,
    node_path: str,
    params: list[Any],
) -> None:
    param_names = {str(param.param_name or "").strip().lower() for param in params}
    param_names.discard("")
    if not param_names:
        return

    selected_global = {item.context_name for item in filtered_env.selected_global_contexts}
    for context in loaded_resource.context_registry.values():
        tail = str(context.context_name or "").split(".")[-1].lower()
        if tail in param_names and context.context_name not in selected_global:
            filtered_env.selected_global_contexts.append(context)
            filtered_env.selected_global_context_ids.append(context.resource_id)
            selected_global.add(context.context_name)

    selected_local = {item.context_name for item in filtered_env.visible_local_context}
    for context in loaded_resource.get_visible_local_context_registry(node_path).values():
        tail = str(context.context_name or "").split(".")[-1].lower()
        if tail in param_names and context.context_name not in selected_local:
            filtered_env.visible_local_context.append(context)
            filtered_env.selected_local_context_ids.append(context.resource_id)
            selected_local.add(context.context_name)


def _node_id(node: dict[str, Any]) -> str | None:
    for key in ("node_id", "id", "field_id"):
        value = node.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _node_name(node: dict[str, Any]) -> str:
    for key in ("node_name", "field_name", "name"):
        value = node.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return _node_id(node) or ""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))[:12000]


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
