import re
from typing import Protocol

from agent.resource_manager.models import BoRegistry

from .models import BoCandidate, BoResolution, DataAccessSpec, NamingSqlProfile


class BoReviewer(Protocol):
    def review(self, *, spec: DataAccessSpec, candidates: list[BoCandidate]) -> str | None: ...


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(value.lower()))


def _cjk_bigrams(value: str) -> set[str]:
    result: set[str] = set()
    for sequence in re.findall(r"[\u4e00-\u9fff]+", value):
        result.update(sequence[index:index + 2] for index in range(len(sequence) - 1))
    return result


def _normalized(value: str) -> str:
    return " ".join(_TOKEN_PATTERN.findall(value.lower()))


class BoResolver:
    def __init__(self, reviewer: BoReviewer | None = None, max_candidates: int = 5):
        self._reviewer = reviewer
        self._max_candidates = min(max(int(max_candidates), 1), 5)

    def resolve(self, *, explicit_bo: str | None, spec: DataAccessSpec, bo_registry: dict[str, BoRegistry], profiles: dict[str, list[NamingSqlProfile]]) -> BoResolution:
        explicit = explicit_bo.strip() if isinstance(explicit_bo, str) else ""
        if explicit:
            match = next((bo for key, bo in bo_registry.items() if explicit == key or explicit == bo.bo_name), None)
            if match is None:
                raise ValueError(f"BO_NOT_LOADED: {explicit}")
            return BoResolution(bo_name=match.bo_name, review_mode="not_required", reasons=["explicit BO scope matched a loaded registry entry"])
        if not bo_registry:
            raise ValueError("BO_NOT_LOADED: no BO candidates")

        query_text = " ".join((*spec.business_terms, *spec.scope_terms, *spec.bo_hints, *spec.filter_requirements))
        query_tokens = _tokens(query_text)
        query_bigrams = _cjk_bigrams(query_text)
        normalized_hints = {_normalized(hint) for hint in spec.bo_hints if _normalized(hint)}
        ranked: list[tuple[float, str, BoCandidate, list[str]]] = []
        for key, bo in bo_registry.items():
            profile_values: list[str] = []
            for profile in profiles.get(key, profiles.get(bo.bo_name, [])):
                profile_values.extend((profile.search_text, *profile.filter_fields, *profile.scope_tags))
            searchable = " ".join((key, bo.bo_name, bo.bo_desc, *(value for prop in bo.property_list for value in (prop.field_name, prop.description or "")), *profile_values))
            token_matches = query_tokens.intersection(_tokens(searchable))
            bigram_matches = query_bigrams.intersection(_cjk_bigrams(searchable))
            exact_hint = _normalized(key) in normalized_hints or _normalized(bo.bo_name) in normalized_hints
            score = float(len(token_matches) * 10 + len(bigram_matches) * 3 + (1000 if exact_hint else 0))
            reasons: list[str] = []
            if exact_hint:
                reasons.append("exact BO hint matched")
            if token_matches:
                reasons.append("term matches: " + ", ".join(sorted(token_matches)[:4]))
            if bigram_matches:
                reasons.append("CJK semantic overlap")
            summary_parts = [bo.bo_desc.strip(), *(prop.description or prop.field_name for prop in bo.property_list[:2])]
            candidate = BoCandidate(bo_name=bo.bo_name, score=score, summary=" | ".join(part for part in summary_parts if part)[:240])
            ranked.append((-score, bo.bo_name, candidate, reasons))
        ranked.sort(key=lambda item: (item[0], item[1]))
        candidates = [item[2] for item in ranked[:self._max_candidates]]
        allowed_names = frozenset(candidate.bo_name for candidate in candidates)
        selected = None
        if self._reviewer is not None:
            try:
                reviewer_candidates = [candidate.model_copy(deep=True) for candidate in candidates]
                selected = self._reviewer.review(spec=spec, candidates=reviewer_candidates)
            except Exception:
                selected = None
        if isinstance(selected, str) and selected.strip() and selected in allowed_names:
            return BoResolution(bo_name=selected, review_mode="llm", reasons=["reviewer selected a supplied BO candidate"])
        return BoResolution(bo_name=candidates[0].bo_name, review_mode="deterministic_fallback", reasons=["deterministic top-1 candidate selected", *ranked[0][3][:3]])
