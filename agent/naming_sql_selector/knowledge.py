import re
from typing import Protocol

from pydantic import Field

from .models import SelectorModel


class DevelopmentKnowledge(SelectorModel):
    text: str
    bo_names: list[str] = Field(default_factory=list)
    naming_sql_names: list[str] = Field(default_factory=list)
    semantic_tags: list[str] = Field(default_factory=list)
    param_aliases: dict[str, list[str]] = Field(default_factory=dict)


class DevelopmentKnowledgeRetriever(Protocol):
    def retrieve(self, site_id: str, query: str, limit: int = 5) -> list[DevelopmentKnowledge]: ...


class NoOpDevelopmentKnowledgeRetriever:
    def retrieve(self, site_id: str, query: str, limit: int = 5) -> list[DevelopmentKnowledge]:
        return []


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()))


class StaticDevelopmentKnowledgeRetriever:
    def __init__(self, entries_by_site: dict[str, list[DevelopmentKnowledge]]):
        self._entries_by_site = entries_by_site

    def retrieve(self, site_id: str, query: str, limit: int = 5) -> list[DevelopmentKnowledge]:
        bounded_limit = min(max(limit, 0), 5)
        if bounded_limit == 0:
            return []
        query_tokens = _tokens(query)
        scored: list[tuple[int, int, DevelopmentKnowledge]] = []
        for index, entry in enumerate(self._entries_by_site.get(site_id, [])):
            searchable = [entry.text, *entry.bo_names, *entry.naming_sql_names, *entry.semantic_tags]
            for name, aliases in entry.param_aliases.items():
                searchable.extend((name, *aliases))
            score = len(query_tokens.intersection(_tokens(" ".join(searchable))))
            if score:
                scored.append((-score, index, entry))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [entry for _, _, entry in scored[:bounded_limit]]
