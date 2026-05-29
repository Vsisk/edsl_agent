from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, List

from agent.environment.resource_filter import LLMResourceFilter
from agent.environment.resource_search_tool import ResourceKeywordSearchTool
from agent.models import NodeDef
from agent.resource_manager.loader.resource_loader import LoadedResource
from agent.resource_manager.loader.tag_utils import tokenize_text
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    ContextRegistry,
    FunctionRegistry,
    LocalContextRegistry,
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


@dataclass(frozen=True, slots=True)
class _ScoredResource:
    resource: object
    score: float
    exact_matches: int
    query_score: float
    index: int


@dataclass(frozen=True, slots=True)
class _ToolSearchResult:
    selected_by_group: dict[str, list]
    matched_groups: set[str]


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


def build_filtered_environment(
    node_info: NodeDef,
    user_query: str,
    registry: LoadedResource,
    top_global_context: int = 5,
    top_local_context: int = 5,
    top_bo: int = 5,
    top_function: int = 5,
    llm_resource_filter: Any | None = None,
) -> FilteredEnvironment:
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
        ),
        "local_context": _select_top_resources(
            visible_local_context,
            weighted_tokens,
            _candidate_limit(top_local_context),
        ),
        "bo": _select_top_resources(
            list(registry.bo_registry.values()),
            weighted_tokens,
            _candidate_limit(top_bo),
        ),
        "function": _select_top_resources(
            list(registry.function_registry.values()),
            weighted_tokens,
            _candidate_limit(top_function),
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
            if len(selected_by_group[group]) >= limits[group]:
                break

    if not found_any:
        return None
    return _ToolSearchResult(selected_by_group=selected_by_group, matched_groups=matched_groups)


def _merge_tool_search_and_fallback(
    *,
    tool_search_result: _ToolSearchResult | None,
    fallback_selected_by_group: dict[str, list],
) -> dict[str, list]:
    if tool_search_result is None:
        return fallback_selected_by_group

    return {
        group: (
            tool_search_result.selected_by_group[group]
            if group in tool_search_result.matched_groups
            else fallback_selected_by_group[group]
        )
        for group in fallback_selected_by_group
    }


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
        for token in tokenize_text(source_values.get(source_name), filter_stop_words=True):
            normalized_token = token.lower()
            weighted_tokens[normalized_token] = max(weighted_tokens.get(normalized_token, 0.0), weight)
    return weighted_tokens


def _select_top_resources(resources: list, weighted_tokens: dict[str, float], top_n: int) -> list:
    if top_n <= 0 or not weighted_tokens:
        return []

    scored_resources: list[_ScoredResource] = []
    for index, resource in enumerate(resources):
        scored_resource = _score_resource(resource, weighted_tokens, index)
        if scored_resource.score > 0:
            scored_resources.append(scored_resource)

    scored_resources.sort(
        key=lambda scored: (
            -scored.score,
            -scored.exact_matches,
            -scored.query_score,
            scored.index,
        )
    )
    return [scored.resource for scored in scored_resources[:top_n]]


def _score_resource(resource: object, weighted_tokens: dict[str, float], index: int) -> _ScoredResource:
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

    return _ScoredResource(
        resource=resource,
        score=score,
        exact_matches=exact_matches,
        query_score=query_score,
        index=index,
    )


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
