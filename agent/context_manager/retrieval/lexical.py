import re
from typing import Any

from agent.context_manager.models import ContextAsset


_USEFUL_KEY = re.compile(r"(name|id|field|param|property|sql)", re.IGNORECASE)


def _normalize(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return " ".join(re.findall(r"[\w]+", value.lower(), re.UNICODE))


def _useful_values(value: Any, key: str = ""):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _useful_values(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _useful_values(child, key)
    elif isinstance(value, str) and _USEFUL_KEY.search(key):
        yield value


class LexicalRetriever:
    def retrieve(self, query: str, assets: list[ContextAsset]) -> list[ContextAsset]:
        normalized_query = _normalize(query)
        query_tokens = normalized_query.split()
        results = []
        for asset in assets:
            candidates = [asset.asset_id, asset.index_text, *_useful_values(asset.content)]
            if any(self._exact_match(candidate, normalized_query, query_tokens) for candidate in candidates):
                results.append(asset.model_copy(deep=True))
        return results

    @staticmethod
    def _exact_match(candidate: str, normalized_query: str, query_tokens: list[str]) -> bool:
        normalized = _normalize(candidate)
        if not normalized:
            return False
        if normalized == normalized_query:
            return True
        candidate_tokens = normalized.split()
        return bool(candidate_tokens) and len(candidate_tokens) <= len(query_tokens) and all(
            token in query_tokens for token in candidate_tokens
        )
