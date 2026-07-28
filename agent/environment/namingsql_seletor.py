from __future__ import annotations

import re
import json
from collections.abc import Callable, Sequence

from agent.llm.llm_client import LLMClient
from agent.llm.generate_by_llm import generate_by_llm
from agent.resource_manager.loader.namingsql_profile_loader import NamingSqlProfile


class NamingSqlSelector:
    """Rule-first NamingSQL selector with an optional bounded LLM choice."""

    def __init__(
        self,
        llm_selector: Callable[[str, list[NamingSqlProfile]], Sequence[str]] | None = None,
        client: LLMClient | None = None,
    ) -> None:
        self.llm_selector = llm_selector
        self.client = client or LLMClient()

    def select(
        self,
        *,
        query: str,
        profiles: list[NamingSqlProfile],
        top_k: int = 5,
    ) -> list[NamingSqlProfile]:
        if top_k <= 0:
            return []
        query_tokens = _tokens(query)
        required_fields = {
            field
            for profile in profiles
            for field in profile.return_fields
            if field.upper() in query_tokens
        }
        candidates = [
            profile
            for profile in profiles
            if required_fields.issubset({field.upper() for field in profile.return_fields})
        ]
        candidates.sort(
            key=lambda profile: (
                -_condition_match_count(profile, query_tokens),
                -int(profile.performance_optimized),
                len(profile.return_fields),
                profile.bo_name,
                profile.namingsql_name,
            )
        )
        candidates = candidates[:top_k]
        if not candidates:
            return candidates

        allowed = {profile.namingsql_name: profile for profile in candidates}
        try:
            if self.llm_selector is not None:
                selected_names = self.llm_selector(query, list(candidates))
            elif self.client.is_usable:
                selected_names = self._select_by_llm(query, candidates)
            else:
                return candidates
        except Exception:
            return candidates
        selected = []
        seen = set()
        for raw_name in selected_names or []:
            name = str(raw_name)
            if name in allowed and name not in seen:
                seen.add(name)
                selected.append(allowed[name])
        return selected or candidates

    def _select_by_llm(
        self,
        query: str,
        candidates: list[NamingSqlProfile],
    ) -> Sequence[str]:
        payload = generate_by_llm(
            prompt_template="namingsql_selector",
            llm_name="base",
            lang="zh",
            client=self.client,
            query=query,
            candidates_json=json.dumps(
                [item.model_dump() for item in candidates],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        names = payload.get("namingsql_names", [])
        return names if isinstance(names, list) else []


def _condition_match_count(profile: NamingSqlProfile, query_tokens: set[str]) -> int:
    return sum(
        bool(_tokens(condition) & query_tokens)
        for condition in profile.where_conditions
    )


def _tokens(value: str) -> set[str]:
    return {
        token.upper()
        for token in re.findall(r"[A-Za-z_][\w$]*", str(value or ""))
    }
