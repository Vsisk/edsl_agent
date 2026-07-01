from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from agent.naming_sql_selector.models import NamingSqlSelectionResult

from agent.environment.resource_filter import BOFilter, ContextFilter, FunctionFilter, LLMResourceFilter, NamingSQLFilter
from agent.environment.resource_search_tool import ResourceKeywordSearchTool
from agent.models import NodeDef
from agent.resource_manager.loader.resource_loader import LoadedResource
from agent.resource_manager.loader.tag_utils import tokenize_text
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    ContextRegistry,
    FilterTarget,
    FunctionRegistry,
    LocalContextRegistry,
    SourceType,
)


@dataclass(slots=True)
class FilteredEnvironment:
    selected_global_context_ids: List[str] = field(default_factory=list)
    selected_local_context_ids: List[str] = field(default_factory=list)
    selected_bo_ids: List[str] = field(default_factory=list)
    selected_function_ids: List[str] = field(default_factory=list)
    selected_global_contexts: List[ContextRegistry] = field(default_factory=list)
    visible_local_context: List[LocalContextRegistry] = field(default_factory=list)
    selected_bos: List[BoRegistry] = field(default_factory=list)
    selected_functions: List[FunctionRegistry] = field(default_factory=list)
    selection_trace: list[dict[str, Any]] = field(default_factory=list)
    naming_sql_selection: NamingSqlSelectionResult | None = None


@dataclass(frozen=True, slots=True)
class _ScoredResource:
    resource: object
    score: float
    exact_matches: int
    query_score: float
    priority_score: float
    index: int


@dataclass(frozen=True, slots=True)
class _ToolSearchResult:
    selected_by_group: dict[str, list]
    matched_groups: set[str]
    broad_match_groups: set[str]


def filter_resources(
    *,
    targets: list[FilterTarget],
    loaded_resource: LoadedResource,
    resource_limits: dict[str, int],
) -> FilteredEnvironment:
    if not targets:
        return FilteredEnvironment(selection_trace=[{"reason": "FILTER_TARGET_EMPTY"}])

    context_targets = [target for target in targets if target.source_type == SourceType.CONTEXT]
    bo_targets = [target for target in targets if target.source_type == SourceType.BO]
    function_targets = [target for target in targets if target.source_type == SourceType.FUNCTION]
    namingsql_targets = [target for target in targets if target.source_type == SourceType.NAMING_SQL]

    context_resources = ContextFilter().filter(
        context_targets,
        loaded_resource.context_registry,
        resource_limits.get("context_count", resource_limits.get("top_global_context", 20)),
    )
    bo_resources = BOFilter().filter(
        bo_targets,
        loaded_resource.bo_registry,
        resource_limits.get("bo_count", resource_limits.get("top_bo", 10)),
    )
    function_resources = FunctionFilter().filter(
        function_targets,
        loaded_resource.function_registry,
        resource_limits.get("function_count", resource_limits.get("top_function", 10)),
    )
    namingsql_resources = NamingSQLFilter().filter(
        namingsql_targets,
        loaded_resource.bo_registry,
        resource_limits.get("namingsql_count", resource_limits.get("top_bo", 10)),
    )
    selected_bos = _merge_filtered_bo_resources(bo_resources, namingsql_resources)
    selection_trace = [
        {
            "target": {
                "source_type": target.source_type.value,
                "domain": target.domain,
                "source_name": target.source_name,
            },
            "matched_domain": target.domain,
            "matched_count": _matched_count_for_target(
                target,
                context_resources=context_resources,
                bo_resources=selected_bos,
                function_resources=function_resources,
            ),
        }
        for target in targets
    ]

    return FilteredEnvironment(
        selected_global_context_ids=[context.resource_id for context in context_resources],
        selected_bo_ids=[bo.resource_id for bo in selected_bos],
        selected_function_ids=[function.resource_id for function in function_resources],
        selected_global_contexts=context_resources,
        selected_bos=selected_bos,
        selected_functions=function_resources,
        selection_trace=selection_trace,
    )


def _merge_filtered_bo_resources(bo_resources: list[BoRegistry], namingsql_resources: list[BoRegistry]) -> list[BoRegistry]:
    by_name: dict[str, BoRegistry] = {}
    for bo in [*bo_resources, *namingsql_resources]:
        existing = by_name.get(bo.bo_name)
        if existing is None:
            by_name[bo.bo_name] = bo
            continue
        properties = _merge_by_attr([*existing.property_list, *bo.property_list], "field_name")
        naming_sql = _merge_by_attr([*existing.naming_sql_list, *bo.naming_sql_list], "sql_name")
        by_name[bo.bo_name] = existing.model_copy(
            update={"property_list": properties, "naming_sql_list": naming_sql},
            deep=True,
        )
    return list(by_name.values())


def _merge_by_attr(items: list[Any], attr: str) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        key = str(getattr(item, attr, "") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _matched_count_for_target(
    target: FilterTarget,
    *,
    context_resources: list[Any],
    bo_resources: list[Any],
    function_resources: list[Any],
) -> int:
    if target.source_type == SourceType.CONTEXT:
        prefix = f"$ctx$.{target.domain}."
        normalized = target.source_name.lower()
        return sum(
            1
            for resource in context_resources
            if str(getattr(resource, "context_name", "")).startswith(prefix)
            and str(getattr(resource, "context_name", "")).split(".")[-1].lower() == normalized
        )
    if target.source_type in {SourceType.BO, SourceType.NAMING_SQL}:
        return sum(1 for resource in bo_resources if getattr(resource, "bo_name", "") == target.domain)
    if target.source_type == SourceType.FUNCTION:
        return sum(
            1
            for resource in function_resources
            if getattr(resource, "func_class", "") == target.domain
            and getattr(resource, "func_name", "") == target.source_name
        )
    return 0


SOURCE_WEIGHTS = (
    ("user_requirement", 3.0),
    ("node_name", 2.0),
    ("description", 1.0),
)
EXACT_MATCH_SCORE = 1.0
SUBSTRING_MATCH_SCORE = 0.5
FUZZY_MATCH_SCORE = 0.3
FUZZY_MATCH_THRESHOLD = 0.8
MIN_PARTIAL_MATCH_LENGTH = 3
CANDIDATE_MULTIPLIER = 5
MAX_CANDIDATES_PER_GROUP = 30
CONTEXT_FIELD_EXACT_BONUS = 2.0
CONTEXT_PARENT_FIELD_PAIR_BONUS = 1.0
BILL_STATEMENT_PRIORITY_SCORE = 1.0
BILL_STATEMENT_TOKENS = {"billstatement", "bill", "statement", "bbbillstatement"}


def build_filtered_environment(
    node_info: NodeDef,
    user_query: str,
    registry: LoadedResource,
    top_global_context: int = 5,
    top_local_context: int = 5,
    top_bo: int = 5,
    top_function: int = 5,
    llm_resource_filter: Any | None = None,
    targets: list[FilterTarget] | None = None,
) -> FilteredEnvironment:
    if targets is not None:
        return filter_resources(
            targets=targets,
            loaded_resource=registry,
            resource_limits={
                "context_count": max(top_global_context, top_local_context, 0),
                "bo_count": max(top_bo, 0),
                "function_count": max(top_function, 0),
                "namingsql_count": max(top_bo, 0),
            },
        )

    visible_local_context = list(registry.get_visible_local_context_registry(node_info.node_path).values())
    weighted_tokens = _build_weighted_tokens(node_info, user_query)
    limits = {
        "global_context": max(top_global_context, 0),
        "local_context": max(top_local_context, 0),
        "bo": max(top_bo, 0),
        "function": max(top_function, 0),
    }
    candidates = {
        "global_context": _select_top_resources(
            list(registry.context_registry.values()),
            weighted_tokens,
            _candidate_limit(top_global_context),
            "global_context",
        ),
        "local_context": _select_top_resources(
            visible_local_context,
            weighted_tokens,
            _candidate_limit(top_local_context),
            "local_context",
        ),
        "bo": _select_top_resources(
            list(registry.bo_registry.values()),
            weighted_tokens,
            _candidate_limit(top_bo),
            "bo",
        ),
        "function": _select_top_resources(
            list(registry.function_registry.values()),
            weighted_tokens,
            _candidate_limit(top_function),
            "function",
        ),
    }

    tool_search_result = _apply_llm_tool_search(
        node_info=node_info,
        user_query=user_query,
        candidates=candidates,
        limits=limits,
        llm_resource_filter=llm_resource_filter,
    )
    fallback_selected_by_group = _apply_llm_filter(
        node_info=node_info,
        user_query=user_query,
        candidates=candidates,
        limits=limits,
        llm_resource_filter=llm_resource_filter,
    )
    selected_by_group = _merge_tool_search_and_fallback(
        tool_search_result=tool_search_result,
        fallback_selected_by_group=fallback_selected_by_group,
    )
    selected_global_contexts = selected_by_group["global_context"]
    selected_local_contexts = selected_by_group["local_context"]
    selected_bos = selected_by_group["bo"]
    selected_functions = selected_by_group["function"]

    return FilteredEnvironment(
        selected_global_context_ids=[context.resource_id for context in selected_global_contexts],
        selected_local_context_ids=[context.resource_id for context in selected_local_contexts],
        selected_bo_ids=[bo.resource_id for bo in selected_bos],
        selected_function_ids=[function.resource_id for function in selected_functions],
        selected_global_contexts=selected_global_contexts,
        visible_local_context=selected_local_contexts,
        selected_bos=selected_bos,
        selected_functions=selected_functions,
    )


def _candidate_limit(top_n: int) -> int:
    if top_n <= 0:
        return 0
    return min(top_n * CANDIDATE_MULTIPLIER, MAX_CANDIDATES_PER_GROUP)


def _apply_llm_tool_search(
    *,
    node_info: NodeDef,
    user_query: str,
    candidates: dict[str, list],
    limits: dict[str, int],
    llm_resource_filter: Any | None,
) -> _ToolSearchResult | None:
    if not any(candidates.values()):
        return None

    filter_service = llm_resource_filter
    if filter_service is None:
        filter_service = LLMResourceFilter()
        if not filter_service.is_usable:
            return None

    search_space = _build_resource_search_space(candidates)
    try:
        command_result = filter_service.plan_resource_search_commands(
            node_info=node_info,
            user_query=user_query,
            search_space=search_space,
            limits=limits,
        )
    except Exception:
        return None

    return _execute_resource_search_commands(
        candidates=candidates,
        search_space=search_space,
        limits=limits,
        command_result=command_result,
    )


def _build_resource_search_space(candidates: dict[str, list]) -> dict[str, list[str]]:
    return {
        group: [_resource_search_text(resource, group) for resource in resources]
        for group, resources in candidates.items()
    }


def _execute_resource_search_commands(
    *,
    candidates: dict[str, list],
    search_space: dict[str, list[str]],
    limits: dict[str, int],
    command_result: dict[str, list[dict[str, str]]],
) -> _ToolSearchResult | None:
    search_tool = ResourceKeywordSearchTool()
    selected_by_group: dict[str, list] = {}
    selected_ids_by_group: dict[str, set[str]] = {}
    matched_groups: set[str] = set()
    broad_match_groups: set[str] = set()
    for group in candidates:
        selected_by_group[group] = []
        selected_ids_by_group[group] = set()

    found_any = False
    for command in command_result.get("commands") or []:
        if not isinstance(command, dict):
            continue
        tool = str(command.get("tool") or "")
        group = str(command.get("group") or "")
        keyword = str(command.get("keyword") or "")
        if tool != search_tool.name or group not in candidates or not keyword:
            continue
        if limits[group] <= 0:
            continue

        is_broad_context_match = _is_broad_context_keyword(group, keyword, search_space[group])
        command_found = False
        for index in search_tool.search(search_space[group], keyword):
            if index < 0 or index >= len(candidates[group]):
                continue
            resource = candidates[group][index]
            resource_id = getattr(resource, "resource_id", "")
            if resource_id in selected_ids_by_group[group]:
                continue
            selected_by_group[group].append(resource)
            selected_ids_by_group[group].add(resource_id)
            found_any = True
            matched_groups.add(group)
            command_found = True
            if len(selected_by_group[group]) >= limits[group]:
                break
        if command_found and is_broad_context_match:
            broad_match_groups.add(group)

    if not found_any:
        return None
    return _ToolSearchResult(
        selected_by_group=selected_by_group,
        matched_groups=matched_groups,
        broad_match_groups=broad_match_groups,
    )


def _merge_tool_search_and_fallback(
    *,
    tool_search_result: _ToolSearchResult | None,
    fallback_selected_by_group: dict[str, list],
) -> dict[str, list]:
    if tool_search_result is None:
        return fallback_selected_by_group

    merged: dict[str, list] = {}
    for group, fallback_resources in fallback_selected_by_group.items():
        if group not in tool_search_result.matched_groups:
            merged[group] = fallback_resources
            continue
        if group in tool_search_result.broad_match_groups:
            limit = len(fallback_resources) or len(tool_search_result.selected_by_group[group])
            merged[group] = _merge_resource_lists(
                fallback_resources,
                tool_search_result.selected_by_group[group],
                limit=limit,
            )
            continue
        merged[group] = tool_search_result.selected_by_group[group]
    return merged


def _is_broad_context_keyword(group: str, keyword: str, items: list[str]) -> bool:
    if group not in {"global_context", "local_context"}:
        return False
    normalized = keyword.strip().lower()
    if normalized.startswith(("$ctx$.", "$local$.", "$iter$.")):
        return False
    matches = ResourceKeywordSearchTool().search(items, keyword)
    return len(matches) > 1


def _merge_resource_lists(primary: list, secondary: list, *, limit: int) -> list:
    selected: list = []
    selected_ids: set[str] = set()
    for resource in [*primary, *secondary]:
        resource_id = getattr(resource, "resource_id", "")
        if resource_id in selected_ids:
            continue
        selected.append(resource)
        selected_ids.add(resource_id)
        if len(selected) >= limit:
            break
    return selected


def _resource_search_text(resource: object, group: str) -> str:
    if group == "bo":
        keywords = [getattr(resource, "bo_name", "")]
        keywords.extend(item.sql_name for item in getattr(resource, "naming_sql_list", []) or [])
    elif group == "function":
        keywords = [getattr(resource, "func_name", "")]
    else:
        keywords = [getattr(resource, "context_name", "")]
    return " ".join(str(keyword) for keyword in keywords if keyword)


def _apply_llm_filter(
    *,
    node_info: NodeDef,
    user_query: str,
    candidates: dict[str, list],
    limits: dict[str, int],
    llm_resource_filter: Any | None,
) -> dict[str, list]:
    selections = {group: resources[: limits[group]] for group, resources in candidates.items()}
    if not any(candidates.values()):
        return selections

    filter_service = llm_resource_filter
    if filter_service is None:
        filter_service = LLMResourceFilter()
        if not filter_service.is_usable:
            return selections

    try:
        llm_result = filter_service.filter_resources(
            node_info=node_info,
            user_query=user_query,
            candidates=candidates,
            limits=limits,
        )
    except Exception:
        return selections

    return {
        group: _select_from_llm_result(candidates[group], llm_result.get(group) or [], limits[group])
        for group in candidates
    }


def _select_from_llm_result(candidates: list, llm_items: list, limit: int) -> list:
    if limit <= 0:
        return []

    candidates_by_id = {resource.resource_id: resource for resource in candidates}
    selected: list = []
    selected_ids: set[str] = set()
    for item in llm_items:
        if isinstance(item, str):
            resource_id = item
        elif isinstance(item, dict):
            resource_id = str(item.get("resource_id") or "")
        else:
            continue
        if resource_id in candidates_by_id and resource_id not in selected_ids:
            selected.append(candidates_by_id[resource_id])
            selected_ids.add(resource_id)
        if len(selected) >= limit:
            return selected

    for resource in candidates:
        if resource.resource_id not in selected_ids:
            selected.append(resource)
        if len(selected) >= limit:
            return selected

    return selected


def _build_weighted_tokens(node_info: NodeDef, user_query: str) -> dict[str, float]:
    source_values = {
        "user_requirement": user_query,
        "node_name": node_info.node_name,
        "description": node_info.description,
    }
    weighted_tokens: dict[str, float] = {}
    for source_name, weight in SOURCE_WEIGHTS:
        for token in tokenize_text(
            source_values.get(source_name),
            filter_stop_words=True,
            include_aliases=source_name == "user_requirement",
        ):
            normalized_token = token.lower()
            weighted_tokens[normalized_token] = max(weighted_tokens.get(normalized_token, 0.0), weight)
    return weighted_tokens


def _select_top_resources(resources: list, weighted_tokens: dict[str, float], top_n: int, group: str) -> list:
    if top_n <= 0 or not weighted_tokens:
        return []

    scored_resources: list[_ScoredResource] = []
    for index, resource in enumerate(resources):
        scored_resource = _score_resource(resource, weighted_tokens, index, group)
        if scored_resource.score > 0:
            scored_resources.append(scored_resource)

    scored_resources.sort(
        key=lambda scored: (
            -scored.score,
            -scored.exact_matches,
            -scored.query_score,
            -scored.priority_score,
            scored.index,
        )
    )
    return [scored.resource for scored in scored_resources[:top_n]]


def _score_resource(resource: object, weighted_tokens: dict[str, float], index: int, group: str) -> _ScoredResource:
    tags = [str(tag).lower() for tag in getattr(resource, "tag", []) if tag]
    score = 0.0
    exact_matches = 0
    query_score = 0.0

    for token, weight in weighted_tokens.items():
        match_score = _best_token_match_score(token, tags)
        if match_score <= 0:
            continue
        weighted_score = weight * match_score
        score += weighted_score
        if weight == 3.0:
            query_score += weighted_score
        if match_score == EXACT_MATCH_SCORE:
            exact_matches += 1

    if group in {"global_context", "local_context"}:
        score += _context_specificity_bonus(resource, weighted_tokens)
    priority_score = _context_priority_score(resource, weighted_tokens, group)

    return _ScoredResource(
        resource=resource,
        score=score,
        exact_matches=exact_matches,
        query_score=query_score,
        priority_score=priority_score,
        index=index,
    )


def _context_specificity_bonus(resource: object, weighted_tokens: dict[str, float]) -> float:
    context_name = str(getattr(resource, "context_name", "") or "")
    parts = [_normalize_resource_alias(part) for part in context_name.split(".") if part]
    query_tokens = set(weighted_tokens)
    has_field = bool(parts and parts[-1] in query_tokens)
    has_parent = any(part in query_tokens for part in parts[:-1])
    bonus = 0.0
    if has_field:
        bonus += CONTEXT_FIELD_EXACT_BONUS
    if has_field and has_parent:
        bonus += CONTEXT_PARENT_FIELD_PAIR_BONUS
    return bonus


def _context_priority_score(resource: object, weighted_tokens: dict[str, float], group: str) -> float:
    if group != "global_context":
        return 0.0
    context_name = str(getattr(resource, "context_name", "") or "").lower()
    if not context_name.startswith("$ctx$.billstatement."):
        return 0.0
    if not (set(weighted_tokens) & BILL_STATEMENT_TOKENS):
        return 0.0
    return BILL_STATEMENT_PRIORITY_SCORE


def _normalize_resource_alias(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _best_token_match_score(token: str, tags: list[str]) -> float:
    best_score = 0.0
    for tag in tags:
        best_score = max(best_score, _match_token(token, tag))
        if best_score == EXACT_MATCH_SCORE:
            return best_score
    return best_score


def _match_token(token: str, tag: str) -> float:
    if token == tag:
        return EXACT_MATCH_SCORE
    if len(token) >= MIN_PARTIAL_MATCH_LENGTH and len(tag) >= MIN_PARTIAL_MATCH_LENGTH:
        if token in tag or tag in token:
            return SUBSTRING_MATCH_SCORE
        if SequenceMatcher(None, token, tag).ratio() >= FUZZY_MATCH_THRESHOLD:
            return FUZZY_MATCH_SCORE
    return 0.0
