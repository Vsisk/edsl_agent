import re
from typing import Iterable, List


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "by",
    "for",
    "from",
    "get",
    "in",
    "is",
    "latest",
    "mask",
    "of",
    "or",
    "stores",
    "the",
    "to",
}

TOKEN_PATTERN = re.compile(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[A-Z]+|\d+|[\u4e00-\u9fff]+")


def build_tags(*values: str | None) -> List[str]:
    tags: List[str] = []
    for index, value in enumerate(values):
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        if index == 0:
            _append_unique(tags, text)
            _append_unique_many(tags, _extract_tokens(text, filter_stop_words=False))
        else:
            _append_unique_many(tags, _extract_tokens(text, filter_stop_words=True))
    return tags


def _extract_tokens(text: str, filter_stop_words: bool) -> List[str]:
    normalized = re.sub(r"[_\-.]+", " ", text)
    tokens = TOKEN_PATTERN.findall(normalized)
    if not filter_stop_words:
        return tokens
    return [token for token in tokens if token.lower() not in STOP_WORDS]


def _append_unique_many(values: List[str], items: Iterable[str]) -> None:
    for item in items:
        _append_unique(values, item)


def _append_unique(values: List[str], item: str) -> None:
    if item and item not in values:
        values.append(item)
