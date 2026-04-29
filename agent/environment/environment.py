from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List

from agent.models import NodeDef
from agent.resource_manager.loader.resource_loader import LoadedResource
from agent.resource_manager.loader.tag_utils import tokenize_text
from agent.resource_manager.models.registry_models import (
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


def build_filtered_environment(
    node_info: NodeDef,
    user_query: str,
    registry: LoadedResource,
    top_global_context: int = 5,
    top_local_context: int = 5,
    top_bo: int = 5,
    top_function: int = 5,
) -> FilteredEnvironment:
    visible_local_context = list(registry.get_visible_local_context_registry(node_info.node_path).values())
    weighted_tokens = _build_weighted_tokens(node_info, user_query)
    selected_global_contexts = _select_top_resources(
        list(registry.context_registry.values()),
        weighted_tokens,
        top_global_context,
    )
    selected_local_contexts = _select_top_resources(
        visible_local_context,
        weighted_tokens,
        top_local_context,
    )
    selected_bos = _select_top_resources(
        list(registry.bo_registry.values()),
        weighted_tokens,
        top_bo,
    )
    selected_functions = _select_top_resources(
        list(registry.function_registry.values()),
        weighted_tokens,
        top_function,
    )

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
