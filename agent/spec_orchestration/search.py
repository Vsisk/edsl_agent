from __future__ import annotations

import math
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
        embedding_client: Any = None,
    ) -> None:
        self.loaded_resource = loaded_resource
        self.naming_sql_retriever = naming_sql_retriever
        self.embedding_client = embedding_client
        self._resource_vector_cache: dict[str, list[float]] = {}

    def search(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        if request.tier == ResourceTier.VISIBLE_VALUE:
            return self._search_visible(request)
        if request.tier == ResourceTier.BO_FIELD:
            return self._search_bo_fields(request)
        if request.tier == ResourceTier.BO_ACCESS:
            return self._search_bo_access(request)
        if request.tier == ResourceTier.BO_SELECT:
            return self._search_bo_select(request)
        if request.tier == ResourceTier.FUNCTION:
            return self._search_functions(request)
        if request.tier == ResourceTier.LITERAL:
            return self._search_literal(request)
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
        ranked = []
        for index, resource in enumerate(resources):
            if getattr(resource, "return_type", None) is None:
                continue
            text = _context_search_text(resource)
            if _contains_negative(text, request.negative_keywords):
                continue
            rank = _context_match_rank(
                resource.context_name,
                request,
                annotation=getattr(resource, "annotation", ""),
                tags=getattr(resource, "tag", []),
            )
            if rank is None:
                continue
            ranked.append(
                (
                    rank,
                    index,
                    ResourceCandidate(
                        candidate_id=resource.resource_id,
                        kind="context",
                        resource=resource,
                        return_type=resource.return_type,
                        evidence=["context name/path match"],
                    ),
                )
            )
        ranked.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in ranked[: request.limit]]

    def _search_bo_fields(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        entries = []
        for bo in self.loaded_resource.bo_registry.values():
            if request.target_bo_name and bo.bo_name != request.target_bo_name:
                continue
            for field in bo.property_list:
                text = _bo_field_search_text(bo, field)
                if _contains_negative(text, request.negative_keywords):
                    continue
                entries.append((bo, field, text))
        scores = self._semantic_scores(request, [item[2] for item in entries])
        ranked = []
        for index, (bo, field, text) in enumerate(entries):
            lexical_rank = _field_lexical_rank(field, request)
            semantic_score = scores[index] if scores is not None else None
            if (
                lexical_rank is None
                and semantic_score is None
                and not _matches(text, request)
            ):
                continue
            ranked.append(
                (
                    lexical_rank if lexical_rank is not None else 9,
                    -(semantic_score if semantic_score is not None else -1.0),
                    index,
                    ResourceCandidate(
                        candidate_id=f"{bo.resource_id}:field:{field.field_name}",
                        kind="bo_field",
                        resource=bo,
                        bo_name=bo.bo_name,
                        field_name=field.field_name,
                        is_key=field.data_type == DataTypeEnum.key,
                        return_type=_property_return_type(field),
                        evidence=[
                            "BO field exact/lexical match"
                            if lexical_rank is not None
                            else "BO field semantic match"
                        ],
                        metadata={
                            "field": field,
                            **(
                                {"embedding_similarity": semantic_score}
                                if semantic_score is not None
                                else {}
                            ),
                        },
                    ),
                )
            )
        ranked.sort(key=lambda item: item[:3])
        return [item[3] for item in ranked[: request.limit]]

    def _search_bo_access(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        return self._search_naming_sql(request)[: request.limit]

    def _search_bo_select(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        target_bo = self.loaded_resource.bo_registry.get(request.target_bo_name or "")
        if target_bo is None:
            return []
        selectable_fields = [
            field
            for field in target_bo.property_list
            if not field.is_list and field.field_name != request.target_field_name
        ]
        explicit_fields = [
            field
            for field in selectable_fields
            if _field_is_explicit_in_query(field, request.query)
        ]
        condition_fields = explicit_fields or [
            field for field in target_bo.property_list
            if field.data_type == DataTypeEnum.key and not field.is_list
        ]
        if not condition_fields:
            return []
        operation = "select" if request.goal.expected_type.is_list else "select_one"
        condition_names = [field.field_name for field in condition_fields]
        return [
            ResourceCandidate(
                candidate_id=(
                    f"{operation}:{target_bo.bo_name}:"
                    f"{','.join(condition_names)}"
                ),
                kind="bo_select",
                resource=target_bo,
                bo_name=target_bo.bo_name,
                field_name=request.target_field_name,
                return_type=ReturnType(
                    data_type="bo",
                    data_type_name=target_bo.bo_name,
                    is_list=request.goal.expected_type.is_list,
                ),
                required_inputs=[
                    ResourceInput(
                        name=field.field_name,
                        return_type=ReturnType(
                            data_type=field.data_type.value,
                            data_type_name=field.data_type_name,
                            is_list=False,
                        ),
                    )
                    for field in condition_fields
                ],
                evidence=[
                    (
                        "query condition field match"
                        if explicit_fields
                        else "primary key fallback"
                    )
                ],
                metadata={
                    "bo": target_bo,
                    "operation": operation,
                    "target_field_name": request.target_field_name,
                    "condition_fields": condition_names,
                },
            )
        ]

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
        entries = []
        for function in self.loaded_resource.function_registry.values():
            if not _return_type_compatible(function.return_type, request.goal.expected_type):
                continue
            text = _function_search_text(function)
            if _contains_negative(text, request.negative_keywords):
                continue
            entries.append((function, text))
        scores = self._semantic_scores(request, [item[1] for item in entries])
        ranked = []
        for index, (function, text) in enumerate(entries):
            lexical = _matches(text, request)
            semantic_score = scores[index] if scores is not None else None
            if not lexical and semantic_score is None:
                continue
            ranked.append(
                (
                    0 if lexical else 1,
                    -(semantic_score if semantic_score is not None else -1.0),
                    index,
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
                        evidence=[
                            "function lexical match"
                            if lexical
                            else "function semantic coarse match"
                        ],
                        metadata=(
                            {"embedding_similarity": semantic_score}
                            if semantic_score is not None
                            else {}
                        ),
                    ),
                )
            )
        ranked.sort(key=lambda item: item[:3])
        return [item[3] for item in ranked[: min(request.limit, 20)]]

    def _semantic_scores(
        self,
        request: GoalSearchRequest,
        documents: list[str],
    ) -> list[float] | None:
        queries = _unique_nonempty([*request.keywords, *request.aliases])
        if self.embedding_client is None or not queries or not documents:
            return None
        try:
            missing_documents = [
                item
                for item in dict.fromkeys(documents)
                if item not in self._resource_vector_cache
            ]
            vectors = self.embedding_client.embed_texts([*queries, *missing_documents])
            _validate_vectors(vectors, len(queries) + len(missing_documents))
            query_vectors = vectors[: len(queries)]
            for document, vector in zip(
                missing_documents,
                vectors[len(queries):],
            ):
                self._resource_vector_cache[document] = vector
            return [
                max(
                    _cosine(query_vector, self._resource_vector_cache[document])
                    for query_vector in query_vectors
                )
                for document in documents
            ]
        except Exception:
            return None

    def _search_literal(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        type_name = str(request.goal.expected_type.data_type_name or "").lower()
        if type_name not in {"str", "string"} or request.goal.expected_type.is_list:
            return []
        value = request.goal.semantic_name.strip()
        if not value:
            return []
        return [
            ResourceCandidate(
                candidate_id=f"literal:{request.goal.goal_id}",
                kind="literal",
                resource=value,
                return_type=request.goal.expected_type.model_copy(deep=True),
                evidence=["string literal fallback"],
                metadata={"value": value},
            )
        ]


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


def _context_search_text(resource: Any) -> str:
    return " ".join(
        [
            resource.context_name,
            getattr(resource, "annotation", ""),
            *getattr(resource, "tag", []),
        ]
    )


def _context_match_rank(
    context_name: str,
    request: GoalSearchRequest,
    *,
    annotation: str,
    tags: list[str],
) -> int | None:
    name = _normalize_path(context_name)
    stripped = _strip_context_prefix(name)
    segments = [item for item in stripped.split(".") if item]
    positives = _unique_nonempty(
        [
            *request.keywords,
            *request.aliases,
            request.goal.semantic_name,
            request.goal.target_field_name or "",
        ]
    )
    for value in positives:
        query = _normalize_path(value)
        query_stripped = _strip_context_prefix(query)
        if query == name:
            return 0
        if query_stripped and query_stripped == stripped:
            return 1
        if query_stripped and stripped.endswith(f".{query_stripped}"):
            return 2
        if query_stripped and segments and query_stripped == segments[-1]:
            return 3
    annotation_text = " ".join([annotation, *tags])
    if _matches(annotation_text, request):
        return 4
    return None


def _bo_field_search_text(bo: Any, field: Any) -> str:
    return (
        f"业务对象：{bo.bo_name} 业务对象含义：{bo.bo_desc} "
        f"字段：{field.field_name} 字段含义：{field.description or ''} "
        f"标签：{' '.join(bo.tag)}"
    )


def _function_search_text(function: Any) -> str:
    inputs = " ".join(
        (
            f"{param.param_name}:{param.data_type.value}/"
            f"{param.data_type_name or ''}"
        )
        for param in function.param_list
    )
    output = (
        f"{function.return_type.data_type.value}/"
        f"{function.return_type.data_type_name or ''}/"
        f"{function.return_type.is_list}"
    )
    return (
        f"函数：{function.func_name} 功能：{function.func_desc} "
        f"类别：{function.func_class} 标签：{' '.join(function.tag)} "
        f"输入：{inputs} 输出：{output}"
    )


def _field_lexical_rank(field: Any, request: GoalSearchRequest) -> int | None:
    field_name = _normalize(field.field_name)
    description = _normalize(field.description or "")
    positives = _unique_nonempty([*request.keywords, *request.aliases])
    for value in positives:
        normalized = _normalize(value)
        if normalized and normalized == field_name:
            return 0
        if normalized and normalized == description:
            return 1
    return 2 if _matches(f"{field.field_name} {field.description or ''}", request) else None


def _return_type_compatible(actual: Any, expected: ReturnType) -> bool:
    if expected.is_list is not None and bool(actual.is_list) != bool(expected.is_list):
        return False
    actual_name = _normalize(actual.data_type_name or "")
    expected_name = _normalize(expected.data_type_name or "")
    if actual_name and expected_name and actual_name != expected_name:
        return False
    actual_type = (
        actual.data_type.value
        if hasattr(actual.data_type, "value")
        else actual.data_type
    )
    if expected.data_type and actual_type:
        compatible_types = {(_normalize(actual_type), _normalize(expected.data_type))}
        if compatible_types <= {("basic", "basic"), ("key", "basic"), ("basic", "key")}:
            return True
        if _normalize(actual_type) != _normalize(expected.data_type):
            return False
    return True


def _contains_negative(text: str, negative_keywords: list[str]) -> bool:
    haystack = _normalize(text)
    return any(
        token and token in haystack
        for value in negative_keywords
        for token in _tokens(value)
    )


def _unique_nonempty(values: list[str]) -> list[str]:
    result = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _validate_vectors(vectors: list[list[float]], expected_count: int) -> None:
    if len(vectors) != expected_count or not vectors:
        raise ValueError("embedding vector count mismatch")
    dimension = len(vectors[0])
    if dimension == 0 or any(len(vector) != dimension for vector in vectors):
        raise ValueError("embedding vector dimension mismatch")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for vector in vectors
        for value in vector
    ):
        raise ValueError("embedding vector contains invalid values")


def _cosine(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _normalize_path(value: str) -> str:
    return re.sub(r"\.+", ".", str(value or "").strip().lower()).strip(".")


def _strip_context_prefix(value: str) -> str:
    return re.sub(r"^\$(?:ctx|local|iter)\$\.", "", value)


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


def _field_is_explicit_in_query(field: Any, query: str) -> bool:
    haystack = _normalize(query)
    field_name = _normalize(field.field_name)
    description = _normalize(field.description or "")
    return bool(
        (field_name and field_name in haystack)
        or (description and description in haystack)
    )


def _normalize(value: str) -> str:
    split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    return re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "", split).lower()
