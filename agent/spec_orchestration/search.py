from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
from typing import Any

from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine_similarity

from agent.llm.generate_by_llm import generate_by_llm
from agent.expression_generation.type_system import TypeDef, TypeRef
from agent.resource_manager.loader.namingsql_profile_loader import NamingSqlProfileLoader
from agent.resource_manager.loader.registry_models import (
    DataTypeEnum,
    PropertyTerm,
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
        function_selector: Any = None,
        bo_domain_selector: Any = None,
        embedding_batch_size: int | None = None,
        bo_search_batch_size: int = 64,
        bo_search_max_workers: int = 4,
    ) -> None:
        self.loaded_resource = loaded_resource
        self.naming_sql_retriever = naming_sql_retriever
        self.embedding_client = embedding_client
        self.function_selector = function_selector
        self.bo_domain_selector = bo_domain_selector
        self.embedding_batch_size = _resolve_embedding_batch_size(
            embedding_client,
            embedding_batch_size,
        )
        if bo_search_batch_size <= 0:
            raise ValueError("bo_search_batch_size must be positive")
        if bo_search_max_workers <= 0:
            raise ValueError("bo_search_max_workers must be positive")
        self.bo_search_batch_size = bo_search_batch_size
        self.bo_search_max_workers = bo_search_max_workers
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
                    rank[0],
                    -rank[1],
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
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item[3] for item in ranked[: request.limit]]

    def _search_bo_fields(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        positives = _unique_nonempty([*request.keywords, *request.aliases])
        allowed_bo_names = self._select_bo_names_for_field_search(request)
        bo_entries = [
            (index, bo)
            for index, bo in enumerate(self.loaded_resource.bo_registry.values())
            if bo.bo_name in allowed_bo_names
        ]
        ranked = []
        batches = list(_batches(bo_entries, self.bo_search_batch_size))
        if len(batches) <= 1 or self.bo_search_max_workers == 1:
            for batch in batches:
                ranked.extend(self._search_bo_field_batch(request, positives, batch))
        else:
            with ThreadPoolExecutor(max_workers=self.bo_search_max_workers) as executor:
                for batch_ranked in executor.map(
                    lambda batch: self._search_bo_field_batch(
                        request,
                        positives,
                        batch,
                    ),
                    batches,
                ):
                    ranked.extend(batch_ranked)
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item[3] for item in ranked[: request.limit]]

    def _search_bo_field_batch(
        self,
        request: GoalSearchRequest,
        positives: list[str],
        bo_entries: list[tuple[int, Any]],
    ) -> list[tuple[int, float, int, ResourceCandidate]]:
        ranked = []
        for bo_index, bo in bo_entries:
            for field in bo.property_list:
                if _property_name_match(
                    field.field_name,
                    request.negative_keywords,
                ) is not None:
                    continue
                match = _property_name_match(field.field_name, positives)
                if match is None:
                    continue
                match_rank, lexical_cosine = match
                ranked.append(
                    (
                        match_rank,
                        -lexical_cosine,
                        bo_index,
                        ResourceCandidate(
                            candidate_id=f"{bo.resource_id}:field:{field.field_name}",
                            kind="bo_field",
                            resource=bo,
                            bo_name=bo.bo_name,
                            field_name=field.field_name,
                            is_key=field.is_key,
                            return_type=_property_return_type(field),
                            evidence=["BO property name match"],
                            metadata={
                                "field": field,
                                "expanded_fields": _expanded_structured_fields(
                                    field,
                                    self.loaded_resource.type_defs,
                                ),
                                "lexical_cosine_similarity": lexical_cosine,
                            },
                        ),
                    )
                )
        return ranked

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
            if field.is_key and not field.is_list
        ]
        if not condition_fields:
            return []
        operation = "select" if request.goal.expected_type.is_list else "select_one"
        condition_names = [field.field_name for field in condition_fields]
        selected_fields = [
            field
            for field in target_bo.property_list
            if field.field_name in {request.target_field_name, *condition_names}
        ]
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
                    "expanded_fields": [
                        expanded
                        for field in selected_fields
                        for expanded in _expanded_structured_fields(
                            field,
                            self.loaded_resource.type_defs,
                        )
                    ],
                },
            )
        ]

    def _search_naming_sql(self, request: GoalSearchRequest) -> list[ResourceCandidate]:
        # NamingSQL is a second-stage lookup: BO selection must commit a target
        # BO before this method inspects that BO's SQL definitions.
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
                    sql.sql_command or "",
                    " ".join(
                        item.linked_field_name or item.param_name
                        for item in sql.param_list
                    ),
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
        selected = self._select_functions_with_llm(request, [item[0] for item in entries])
        if selected:
            by_id = {function.resource_id: function for function, _ in entries}
            result = []
            for resource_id in selected:
                function = by_id.get(resource_id)
                if function is None:
                    continue
                result.append(_function_candidate(function, evidence="function LLM selector match"))
            if result:
                return result[: min(request.limit, 20)]
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
                    _function_candidate(
                        function,
                        evidence=(
                            "function lexical match"
                            if lexical
                            else "function semantic coarse match"
                        ),
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

    def _select_functions_with_llm(
        self,
        request: GoalSearchRequest,
        functions: list[Any],
    ) -> list[str]:
        if self.function_selector is None or not functions:
            return []
        summaries = [_function_summary(function) for function in functions]
        try:
            selected = self.function_selector(
                query=_selector_query(request),
                functions=summaries,
                request=request,
            )
        except Exception:
            return []
        if isinstance(selected, dict):
            selected = selected.get("resource_ids") or selected.get("function_ids")
        return [
            str(item)
            for item in (selected or [])
            if isinstance(item, str) and item
        ]

    def _select_bo_names_for_field_search(self, request: GoalSearchRequest) -> set[str]:
        if request.target_bo_name:
            return {request.target_bo_name}
        all_names = [bo.bo_name for bo in self.loaded_resource.bo_registry.values()]
        if self.bo_domain_selector is None:
            return set(all_names)
        try:
            selected = self.bo_domain_selector(
                query=_selector_query(request),
                bo_domains=list(self.loaded_resource.domain_registry.bo_domains or all_names),
                request=request,
            )
        except Exception:
            return set(all_names)
        if isinstance(selected, dict):
            selected = selected.get("bo_names") or selected.get("domains")
        allowed = {
            str(item)
            for item in (selected or [])
            if isinstance(item, str) and item in set(all_names)
        }
        return allowed or set(all_names)

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
            query_vectors = self.embedding_client.embed_texts(queries)
            _validate_vectors(query_vectors, len(queries))
            pending_vectors: dict[str, list[float]] = {}
            for offset in range(0, len(missing_documents), self.embedding_batch_size):
                batch = missing_documents[offset:offset + self.embedding_batch_size]
                batch_vectors = self.embedding_client.embed_texts(batch)
                _validate_vectors(batch_vectors, len(batch))
                if any(
                    len(vector) != len(query_vectors[0])
                    for vector in batch_vectors
                ):
                    raise ValueError("embedding vector dimension mismatch")
                pending_vectors.update(zip(batch, batch_vectors))
            self._resource_vector_cache.update(pending_vectors)
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
        field.data_type.value
    )
    return ReturnType(
        data_type=data_type,
        data_type_name=field.data_type_name,
        is_list=field.is_list,
    )


def _expanded_structured_fields(
    field: Any,
    type_defs: list[TypeDef],
    *,
    max_depth: int = 6,
) -> list[PropertyTerm]:
    owner_type = _property_type_ref(field)
    if owner_type is None:
        return []
    result: list[PropertyTerm] = []
    _append_expanded_fields(
        result,
        parent_name=str(field.field_name),
        owner_type=owner_type,
        type_defs={_type_key(type_def.owner_type): type_def for type_def in type_defs},
        stack=(),
        depth=0,
        max_depth=max_depth,
    )
    return result


def _append_expanded_fields(
    result: list[PropertyTerm],
    *,
    parent_name: str,
    owner_type: TypeRef,
    type_defs: dict[tuple[Any, ...], TypeDef],
    stack: tuple[tuple[Any, ...], ...],
    depth: int,
    max_depth: int,
) -> None:
    key = _type_key(owner_type)
    if key in stack or depth >= max_depth:
        return
    type_def = type_defs.get(key)
    if type_def is None:
        return
    next_stack = (*stack, key)
    for field_name, type_ref in type_def.fields.items():
        normalized = _property_term_type(type_ref)
        if normalized is None:
            continue
        expanded_name = f"{parent_name}.{field_name}"
        result.append(
            PropertyTerm(
                field_name=expanded_name,
                data_type=normalized[0],
                data_type_name=normalized[1],
                is_list=normalized[2],
            )
        )
        nested_owner = _structured_type_ref(type_ref)
        if nested_owner is not None:
            _append_expanded_fields(
                result,
                parent_name=expanded_name,
                owner_type=nested_owner,
                type_defs=type_defs,
                stack=next_stack,
                depth=depth + 1,
                max_depth=max_depth,
            )


def _property_type_ref(field: Any) -> TypeRef | None:
    data_type = getattr(field, "data_type", None)
    kind = data_type.value if hasattr(data_type, "value") else str(data_type or "")
    if kind not in {"logic", "extattr"}:
        return None
    data_type_name = str(getattr(field, "data_type_name", "") or "")
    if not data_type_name:
        return None
    return TypeRef(kind=kind, name=data_type_name)


def _structured_type_ref(type_ref: TypeRef) -> TypeRef | None:
    current = type_ref.element_type if type_ref.kind == "list" else type_ref
    if current is None or current.kind not in {"logic", "extattr"} or not current.name:
        return None
    return TypeRef(kind=current.kind, name=current.name)


def _property_term_type(type_ref: TypeRef) -> tuple[DataTypeEnum, str, bool] | None:
    is_list = type_ref.kind == "list"
    current = type_ref.element_type if is_list else type_ref
    if current is None or current.kind not in {"key", "bo", "logic", "basic", "extattr"}:
        return None
    if not current.name:
        return None
    return DataTypeEnum(current.kind), current.name, is_list


def _type_key(type_ref: TypeRef | None) -> tuple[Any, ...]:
    if type_ref is None:
        return ()
    return (
        type_ref.kind,
        type_ref.name,
        _type_key(type_ref.element_type),
        _type_key(type_ref.key_type),
        _type_key(type_ref.value_type),
        type_ref.nullable,
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
) -> tuple[int, float] | None:
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
            return 0, 1.0
        if query_stripped and query_stripped == stripped:
            return 1, 1.0
        if query_stripped and stripped.endswith(f".{query_stripped}"):
            return 2, 1.0
        if query_stripped and segments and query_stripped == segments[-1]:
            return 3, 1.0
    annotation_text = " ".join([annotation, *tags])
    if _matches(annotation_text, request):
        return 4, 1.0
    score = _keyword_cosine_score(
        " ".join([context_name, annotation, *tags]),
        positives,
    )
    if score >= 0.75:
        return 5, score
    return None


def _keyword_cosine_score(text: str, keywords: list[str]) -> float:
    left = _name_tokens(text)
    right = _name_tokens(" ".join(keywords))
    if not left or not right:
        return 0.0
    return _token_cosine(left, right)


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


def _function_summary(function: Any) -> dict[str, Any]:
    return {
        "resource_id": function.resource_id,
        "domain": function.func_class,
        "name": function.func_name,
        "description": function.func_desc,
        "tags": list(function.tag),
        "params": [
            {
                "name": param.param_name,
                "data_type": param.data_type.value,
                "data_type_name": param.data_type_name,
                "is_list": param.is_list,
            }
            for param in function.param_list
        ],
        "return_type": {
            "data_type": function.return_type.data_type.value,
            "data_type_name": function.return_type.data_type_name,
            "is_list": function.return_type.is_list,
        },
    }


def _function_candidate(
    function: Any,
    *,
    evidence: str,
    metadata: dict[str, Any] | None = None,
) -> ResourceCandidate:
    return ResourceCandidate(
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
        evidence=[evidence],
        metadata=metadata or {},
    )


def _selector_query(request: GoalSearchRequest) -> str:
    return " ".join(
        _unique_nonempty(
            [
                request.query,
                request.goal.semantic_name,
                request.target_bo_name or "",
                request.target_field_name or "",
                *request.keywords,
                *request.aliases,
            ]
        )
    )


class LLMFunctionSelector:
    def __init__(self, *, decision_fn: Any = generate_by_llm) -> None:
        self.decision_fn = decision_fn

    def __call__(
        self,
        *,
        query: str,
        functions: list[dict[str, Any]],
        request: GoalSearchRequest,
    ) -> list[str]:
        raw = self.decision_fn(
            prompt_template="spec_orchestrator_function_search",
            llm_name="base",
            lang="zh",
            query=query[:4000],
            goal_json=json.dumps(
                request.goal.model_dump(mode="json"),
                ensure_ascii=False,
                default=str,
            )[:4000],
            functions_json=json.dumps(
                functions,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )[:20000],
        )
        return _selected_strings(raw, keys=("resource_ids", "function_ids"))


class LLMBoDomainSelector:
    def __init__(self, *, decision_fn: Any = generate_by_llm) -> None:
        self.decision_fn = decision_fn

    def __call__(
        self,
        *,
        query: str,
        bo_domains: list[str],
        request: GoalSearchRequest,
    ) -> list[str]:
        raw = self.decision_fn(
            prompt_template="spec_orchestrator_bo_domain_search",
            llm_name="base",
            lang="zh",
            query=query[:4000],
            goal_json=json.dumps(
                request.goal.model_dump(mode="json"),
                ensure_ascii=False,
                default=str,
            )[:4000],
            bo_domains_json=json.dumps(
                bo_domains,
                ensure_ascii=False,
                separators=(",", ":"),
            )[:12000],
        )
        return _selected_strings(raw, keys=("bo_names", "domains"))


def _selected_strings(raw: Any, *, keys: tuple[str, ...]) -> list[str]:
    if isinstance(raw, dict):
        values = []
        for key in keys:
            if isinstance(raw.get(key), list):
                values = raw[key]
                break
    else:
        values = raw
    return [
        str(item)
        for item in (values or [])
        if isinstance(item, str) and item
    ]


def _property_name_match(
    field_name: str,
    keywords: list[str],
) -> tuple[int, float] | None:
    normalized_name = _normalize(field_name)
    compact_name = normalized_name.replace("_", "")
    field_tokens = _name_tokens(field_name)
    best_match: tuple[int, float] | None = None
    for value in _unique_nonempty(keywords):
        normalized_keyword = _normalize(value)
        compact_keyword = normalized_keyword.replace("_", "")
        if normalized_keyword and normalized_keyword == normalized_name:
            candidate = (0, 1.0)
        elif compact_keyword and compact_keyword == compact_name:
            candidate = (1, 1.0)
        elif compact_keyword and (
            compact_name.endswith(compact_keyword)
            or compact_keyword.endswith(compact_name)
        ):
            candidate = (2, 1.0)
        else:
            similarity = _token_cosine(field_tokens, _name_tokens(value))
            if similarity < 0.75:
                continue
            candidate = (3, similarity)
        if (
            best_match is None
            or candidate[0] < best_match[0]
            or (candidate[0] == best_match[0] and candidate[1] > best_match[1])
        ):
            best_match = candidate
    return best_match


def _name_tokens(value: str) -> list[str]:
    split_acronym = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", str(value or ""))
    split_camel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", split_acronym)
    return re.findall(r"[a-z0-9]+", split_camel.lower().replace("_", " "))


def _token_cosine(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    left_vector, right_vector = _token_feature_vectors(left, right)
    similarity = sklearn_cosine_similarity(
        [left_vector],
        [right_vector],
    )[0][0]
    return max(0.0, min(1.0, float(similarity)))


def _token_feature_vectors(
    left: list[str],
    right: list[str],
) -> tuple[list[float], list[float]]:
    features = list(dict.fromkeys(right))
    assignments: list[tuple[str, float]] = []
    for token in left:
        matches = [
            (candidate, _token_similarity(token, candidate))
            for candidate in right
        ]
        feature, score = max(matches, key=lambda item: item[1])
        if score == 0.0:
            feature = token
            if feature not in features:
                features.append(feature)
        assignments.append((feature, score or 1.0))
    feature_indexes = {feature: index for index, feature in enumerate(features)}
    left_vector = [0.0] * len(features)
    right_vector = [0.0] * len(features)
    for feature, weight in assignments:
        left_vector[feature_indexes[feature]] += weight
    for token in right:
        right_vector[feature_indexes[token]] += 1.0
    return left_vector, right_vector


def _token_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 3 and _is_subsequence(shorter, longer):
        return len(shorter) / len(longer)
    return 0.0


def _is_subsequence(shorter: str, longer: str) -> bool:
    position = 0
    for character in longer:
        if position < len(shorter) and shorter[position] == character:
            position += 1
    return position == len(shorter)


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


def _batches(values: list[Any], batch_size: int) -> list[list[Any]]:
    return [
        values[offset:offset + batch_size]
        for offset in range(0, len(values), batch_size)
    ]


def _resolve_embedding_batch_size(
    embedding_client: Any,
    configured_size: int | None,
) -> int:
    if configured_size is not None:
        if configured_size <= 0:
            raise ValueError("embedding_batch_size must be positive")
        return configured_size
    settings = getattr(embedding_client, "settings", None)
    provider_size = getattr(settings, "local_embedding_batch_size", None)
    if isinstance(provider_size, int) and not isinstance(provider_size, bool):
        return provider_size if provider_size > 0 else 64
    return 64


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
