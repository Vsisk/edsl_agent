from __future__ import annotations

import re
from typing import Any

from agent.resource_manager.loader.namingsql_profile_loader import NamingSqlProfileLoader
from agent.resource_manager.loader.registry_models import (
    DataTypeEnum,
    ReturnType,
)
from agent.resource_manager.loader.resource_loader import LoadedResource

from .models import (
    GoalSearchRequest,
    ResourceCandidate,
    ResourceInput,
    ResourceTier,
)


class OrchestratorResourceSearch:
    def __init__(
        self,
        loaded_resource: LoadedResource,
        *,
        naming_sql_retriever: Any = None,
    ) -> None:
        self.loaded_resource = loaded_resource
        self.naming_sql_retriever = naming_sql_retriever

    def search(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        if request.tier == ResourceTier.VISIBLE_VALUE:
            return self._search_visible(request)
        if request.tier == ResourceTier.BO_FIELD:
            return self._search_bo_fields(request)
        if request.tier == ResourceTier.BO_ACCESS:
            return self._search_bo_access(request)
        if request.tier == ResourceTier.FUNCTION:
            return self._search_functions(request)
        return []

    def _search_visible(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        local_resources = (
            self.loaded_resource.get_visible_local_context_registry(request.node_path).values()
            if request.node_path
            else []
        )
        resources = [
            *self.loaded_resource.context_registry.values(),
            *local_resources,
        ]
        result = []
        for resource in resources:
            if getattr(resource, "return_type", None) is None:
                continue
            text = " ".join(
                [
                    resource.context_name,
                    getattr(resource, "annotation", ""),
                    *getattr(resource, "tag", []),
                ]
            )
            if not _matches(text, request):
                continue
            result.append(
                ResourceCandidate(
                    candidate_id=resource.resource_id,
                    kind="context",
                    resource=resource,
                    return_type=resource.return_type,
                    evidence=["context keyword match"],
                )
            )
        return result[: request.limit]

    def _search_bo_fields(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        result = []
        for bo in self.loaded_resource.bo_registry.values():
            if request.target_bo_name and bo.bo_name != request.target_bo_name:
                continue
            for field in bo.property_list:
                text = " ".join(
                    [
                        bo.bo_name,
                        bo.bo_desc,
                        field.field_name,
                        field.description or "",
                        *bo.tag,
                    ]
                )
                if not _matches(text, request):
                    continue
                result.append(
                    ResourceCandidate(
                        candidate_id=f"{bo.resource_id}:field:{field.field_name}",
                        kind="bo_field",
                        resource=bo,
                        bo_name=bo.bo_name,
                        field_name=field.field_name,
                        is_key=field.data_type == DataTypeEnum.key,
                        return_type=_property_return_type(field),
                        evidence=["BO field keyword match"],
                        metadata={"field": field},
                    )
                )
        return result[: request.limit]

    def _search_bo_access(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        result = [*self._search_naming_sql(request)]
        target_bo = self.loaded_resource.bo_registry.get(request.target_bo_name or "")
        if target_bo is None:
            return result[: request.limit]
        target_keys = [
            field for field in target_bo.property_list
            if field.data_type == DataTypeEnum.key and not field.is_list
        ]
        for target_key in target_keys:
            for bo in self.loaded_resource.bo_registry.values():
                if bo.bo_name == target_bo.bo_name:
                    continue
                for field in bo.property_list:
                    if (
                        _normalize(field.field_name) != _normalize(target_key.field_name)
                        or field.data_type_name != target_key.data_type_name
                        or field.is_list != target_key.is_list
                    ):
                        continue
                    result.append(
                        ResourceCandidate(
                            candidate_id=(
                                f"relation:{bo.bo_name}:{field.field_name}"
                                f"->{target_bo.bo_name}:{target_key.field_name}"
                            ),
                            kind="relation",
                            resource=bo,
                            bo_name=bo.bo_name,
                            field_name=field.field_name,
                            return_type=_property_return_type(field),
                            evidence=["same key name", "compatible key type"],
                            metadata={
                                "target_bo_name": target_bo.bo_name,
                                "target_key_field": target_key.field_name,
                            },
                        )
                    )
        return result[: request.limit]

    def _search_naming_sql(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        target_bo_name = request.target_bo_name
        if not target_bo_name:
            return []
        bo = self.loaded_resource.bo_registry.get(target_bo_name)
        if bo is None:
            return []
        sql_defs = list(bo.naming_sql_list)
        if self.naming_sql_retriever is not None and sql_defs:
            query_terms = [
                *request.keywords,
                *request.aliases,
                request.target_field_name or "",
            ]
            query = " ".join(item for item in query_terms if item)
            profiles = NamingSqlProfileLoader().load_bo(bo)
            selected = self.naming_sql_retriever.select(
                query=query,
                profiles=profiles,
                top_k=request.limit,
            )
            selected_names = {item.namingsql_name for item in selected}
            sql_defs = [item for item in sql_defs if item.sql_name in selected_names]
        result = []
        for sql in sql_defs:
            text = " ".join(
                [
                    sql.naming_sql_id,
                    sql.sql_name,
                    sql.sql_description or "",
                    sql.label_name or "",
                ]
            )
            if request.keywords and not _matches(text, request):
                continue
            result.append(
                ResourceCandidate(
                    candidate_id=f"naming_sql:{bo.bo_name}:{sql.naming_sql_id}",
                    kind="naming_sql",
                    resource=sql,
                    bo_name=bo.bo_name,
                    return_type=ReturnType(
                        data_type="bo", data_type_name=bo.bo_name, is_list=False
                    ),
                    required_inputs=[
                        ResourceInput(
                            name=param.param_name,
                            return_type=ReturnType(
                                data_type=param.data_type,
                                data_type_name=param.data_type_name,
                                is_list=param.is_list,
                            ),
                        )
                        for param in sql.param_list
                    ],
                    evidence=["canonical NamingSQL match"],
                    metadata={"bo": bo},
                )
            )
        return result

    def _search_functions(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        result = []
        for function in self.loaded_resource.function_registry.values():
            text = " ".join(
                [
                    function.func_name,
                    function.func_desc,
                    function.func_class,
                    *function.tag,
                ]
            )
            if not _matches(text, request):
                continue
            result.append(
                ResourceCandidate(
                    candidate_id=function.resource_id,
                    kind="function",
                    resource=function,
                    return_type=ReturnType(
                        data_type=function.return_type.data_type.value,
                        data_type_name=function.return_type.data_type_name,
                        is_list=function.return_type.is_list,
                    ),
                    required_inputs=[
                        ResourceInput(
                            name=param.param_name,
                            return_type=ReturnType(
                                data_type=param.data_type.value,
                                data_type_name=param.data_type_name,
                                is_list=param.is_list,
                            ),
                        )
                        for param in function.param_list
                    ],
                    evidence=["function keyword match"],
                )
            )
        return result[: request.limit]


def _property_return_type(field: Any) -> ReturnType:
    data_type = (
        DataTypeEnum.basic.value
        if field.data_type == DataTypeEnum.key
        else field.data_type.value
    )
    return ReturnType(
        data_type=data_type,
        data_type_name=field.data_type_name,
        is_list=field.is_list,
    )


def _matches(text: str, request: GoalSearchRequest) -> bool:
    haystack = _normalize(text)
    positive = [
        *request.keywords,
        *request.aliases,
        request.goal.semantic_name,
        request.goal.target_field_name or "",
    ]
    negative = [_normalize(item) for item in request.negative_keywords if item]
    if any(item and item in haystack for item in negative):
        return False
    return any(
        token and token in haystack
        for value in positive
        for token in _tokens(value)
    )


def _tokens(value: str) -> list[str]:
    normalized = _normalize(value)
    parts = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized)
    return [item for item in [normalized, *parts] if len(item) >= 2]


def _normalize(value: str) -> str:
    split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    return re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "", split).lower()
