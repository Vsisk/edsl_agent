from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent.llm.generate_by_llm import generate_by_llm
from agent.models import ValueLogicResult, ValueLogicSource, ValueReturnType
from agent.resource_manager.loader.namingsql_profile_loader import NamingSqlProfile, NamingSqlProfileLoader
from agent.resource_manager.loader.registry_models import BoRegistry


class SqlBoSelection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bo_name: str | None = None


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
            selected = SqlBoSelection.model_validate(raw).bo_name
        except Exception:
            return None
        if selected in bo_registry:
            return selected
        return None


class SqlBranchResolver:
    def __init__(
        self,
        *,
        bo_selector: Callable[..., str | None] | SqlBranchBoSelector,
        naming_sql_selector_factory: Callable[[], Any],
    ) -> None:
        self.bo_selector = bo_selector
        self.naming_sql_selector_factory = naming_sql_selector_factory

    def resolve(
        self,
        *,
        query: str,
        node: dict[str, Any],
        bo_registry: dict[str, BoRegistry],
        context_pack: Any,
    ) -> ValueLogicResult | None:
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


def _node_id(node: dict[str, Any]) -> str | None:
    for key in ("node_id", "id", "field_id"):
        value = node.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))[:12000]


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
