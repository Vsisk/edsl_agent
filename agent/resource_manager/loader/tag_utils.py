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
CAMEL_CASE_BOUNDARY_PATTERN = re.compile(r"[a-z][A-Z]")
ALPHANUM_PATTERN = re.compile(r"[0-9A-Za-z]+")


def tokenize_text(text: str | None, filter_stop_words: bool = True, include_aliases: bool = True) -> List[str]:
    if not text:
        return []
    return _extract_tokens(str(text), filter_stop_words=filter_stop_words, include_aliases=include_aliases)


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
            _append_unique_many(tags, tokenize_text(text, filter_stop_words=False, include_aliases=False))
        else:
            if not re.search(r"\s", text):
                _append_unique(tags, text)
            _append_unique_many(tags, tokenize_text(text, filter_stop_words=True, include_aliases=False))
    return tags


def _extract_tokens(text: str, filter_stop_words: bool, include_aliases: bool) -> List[str]:
    tokens: List[str] = []
    for raw_segment in text.split():
        normalized_segment = re.sub(r"[_\-.]+", " ", raw_segment)
        for segment in normalized_segment.split():
            if include_aliases and _should_preserve_compound_token(segment):
                tokens.append(segment)
            tokens.extend(TOKEN_PATTERN.findall(segment))
            if include_aliases:
                _append_aliases(tokens, segment, filter_stop_words)
        if include_aliases:
            _append_aliases(tokens, raw_segment, filter_stop_words)
    if not filter_stop_words:
        return tokens
    return [token for token in tokens if token.lower() not in STOP_WORDS]


def _should_preserve_compound_token(token: str) -> bool:
    return bool(CAMEL_CASE_BOUNDARY_PATTERN.search(token))


def _compact_ascii_token(value: str) -> str:
    return "".join(ALPHANUM_PATTERN.findall(value)).lower()


def _append_aliases(tokens: List[str], segment: str, filter_stop_words: bool) -> None:
    for ascii_token in ALPHANUM_PATTERN.findall(segment):
        compact = ascii_token.lower()
        if len(compact) < 3:
            continue
        if filter_stop_words and compact in STOP_WORDS:
            continue
        _append_unique(tokens, compact)

    compact = _compact_ascii_token(segment)
    if len(compact) < 3:
        return
    if filter_stop_words and compact in STOP_WORDS:
        return
    _append_unique(tokens, compact)


def _append_unique_many(values: List[str], items: Iterable[str]) -> None:
    for item in items:
        _append_unique(values, item)


def _append_unique(values: List[str], item: str) -> None:
    if item and item not in values:
        values.append(item)
