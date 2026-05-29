import re
from typing import List


class ResourceKeywordSearchTool:
    name = "resource_keyword_search"

    def search(self, items: list[str], keyword: str) -> List[int]:
        normalized_keyword = _normalize_search_text(keyword)
        compact_keyword = _compact_search_text(keyword)
        if not normalized_keyword and not compact_keyword:
            return []

        matched_indices: List[int] = []
        for index, item in enumerate(items):
            if _matches(item, normalized_keyword, compact_keyword):
                matched_indices.append(index)
        return matched_indices


def _matches(item: str, normalized_keyword: str, compact_keyword: str) -> bool:
    normalized_item = _normalize_search_text(item)
    if normalized_keyword and normalized_keyword in normalized_item:
        return True

    compact_item = _compact_search_text(item)
    return bool(compact_keyword and compact_keyword in compact_item)


def _normalize_search_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _compact_search_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value).lower())
