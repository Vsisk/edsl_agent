import re
from typing import Any, Protocol

from agent.resource_manager.models import BoRegistry

from .knowledge import DevelopmentKnowledge, DevelopmentKnowledgeRetriever, NoOpDevelopmentKnowledgeRetriever
from .models import (BoCandidate, BoResolution, DataAccessSpec, FallbackNamingSql,
    NamingSqlProfile, NamingSqlReviewCandidate, NamingSqlSelectionRequest,
    NamingSqlSelectionResult, ParamBinding, ParamBindingPlan, RejectedNamingSql,
    SelectedNamingSql)
from .spec_generator import DataAccessSpecGenerator, MAX_TERM_CHARS


class BoReviewer(Protocol):
    def review(self, *, spec: DataAccessSpec, candidates: list[BoCandidate]) -> str | None: ...


class NamingSqlReviewer(Protocol):
    def review(self, *, spec: DataAccessSpec, candidates: list[NamingSqlReviewCandidate]) -> str | None: ...


class NamingSqlCandidateRetriever(Protocol):
    def retrieve(self, *, spec: DataAccessSpec, profiles: list[NamingSqlProfile],
                 knowledge: list[DevelopmentKnowledge], limit: int = 30) -> list[NamingSqlProfile]: ...


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
                reviewer_spec = spec.model_copy(deep=True)
                selected = self._reviewer.review(spec=reviewer_spec, candidates=reviewer_candidates)
            except Exception:
                selected = None
        if isinstance(selected, str) and selected.strip() and selected in allowed_names:
            return BoResolution(bo_name=selected, review_mode="llm", reasons=["reviewer selected a supplied BO candidate"])
        return BoResolution(bo_name=candidates[0].bo_name, review_mode="deterministic_fallback", reasons=["deterministic top-1 candidate selected", *ranked[0][3][:3]])


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", value).strip()[:MAX_TERM_CHARS] if isinstance(value, str) else ""


def _key(value: Any) -> str:
    return "".join(_TOKEN_PATTERN.findall(_compact(value).lower()))


_TYPE_FAMILIES = {
    "numeric": {"byte", "short", "int", "integer", "long", "float", "double", "decimal", "numeric", "number", "bigdecimal"},
    "string": {"str", "string", "char", "varchar", "text", "character"},
    "boolean": {"bool", "boolean"}, "date": {"date", "localdate"},
    "datetime": {"datetime", "timestamp", "instant", "localdatetime"},
}
_GENERIC_SEMANTIC = {"id", "identifier", "date", "code", "no", "number", "name", "value", "type", "key"}


def _type_family(value: str) -> str:
    normalized = _key(value)
    # Qualified Java/.NET wrapper names normalize to a suffix such as java.lang.Long -> javalanglong.
    for family, aliases in _TYPE_FAMILIES.items():
        if normalized in aliases or any(normalized.endswith(alias) for alias in aliases): return family
    return ""


def _type_ok(param_type: str, value_type: str) -> bool:
    left, right = _type_family(param_type), _type_family(value_type)
    if not left or not right:
        return True
    return left == right


def _canonical_requirement(value: str) -> str:
    # The left operand is the field for ordinary predicates; plain requirements remain intact.
    match = re.match(r"\s*([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)\s*(?:=|!=|<>|<=|>=|<|>|\bIN\b|\bLIKE\b|\bBETWEEN\b|\bIS\b)", value, re.I)
    return _key(match.group(1).split(".")[-1] if match else value)


class LocalNamingSqlCandidateRetriever:
    def __init__(self, max_candidates: int = 30):
        self._max_candidates = min(max(int(max_candidates), 1), 30)

    def retrieve(self, *, spec: DataAccessSpec, profiles: list[NamingSqlProfile],
                 knowledge: list[DevelopmentKnowledge], limit: int = 30) -> list[NamingSqlProfile]:
        bounded = min(max(int(limit), 1), self._max_candidates, 30)
        terms = _tokens(" ".join((*spec.business_terms, *spec.scope_terms, *spec.filter_requirements, *spec.bo_hints)))
        recommended = {_key(name) for item in knowledge for name in item.naming_sql_names if _key(name)}
        ranked = []
        for profile in profiles:
            searchable = " ".join((profile.sql_name, profile.label_name, profile.sql_description,
                profile.search_text, *profile.filter_fields, *profile.scope_tags, *(p.name for p in profile.params)))
            explicit = _key(profile.sql_name) in recommended or _key(profile.naming_sql_id) in recommended
            overlap = len(terms.intersection(_tokens(searchable)))
            if explicit or overlap or not terms:
                ranked.append((-(10000 if explicit else 0) - overlap, profile.sql_name, profile.naming_sql_id, profile))
        ranked.sort(key=lambda item: item[:3])
        return [item[3] for item in ranked[:bounded]]


class NamingSqlSelector:
    def __init__(self, knowledge_retriever: DevelopmentKnowledgeRetriever | None = None,
                 spec_generator: DataAccessSpecGenerator | None = None,
                 bo_resolver: BoResolver | None = None, reviewer: NamingSqlReviewer | None = None,
                 candidate_retriever: NamingSqlCandidateRetriever | None = None):
        self._retriever = knowledge_retriever or getattr(spec_generator, "_retriever", None) or NoOpDevelopmentKnowledgeRetriever()
        self._spec_generator = spec_generator
        self._bo_resolver = bo_resolver or BoResolver()
        self._reviewer = reviewer
        self._candidate_retriever = candidate_retriever or LocalNamingSqlCandidateRetriever()

    def _knowledge(self, request: NamingSqlSelectionRequest) -> list[DevelopmentKnowledge]:
        try:
            raw = self._retriever.retrieve(request.site_id, request.query[:4000], limit=5)
        except Exception:
            raw = []
        result: list[DevelopmentKnowledge] = []
        for item in raw if isinstance(raw, list) else []:
            try:
                result.append(item if isinstance(item, DevelopmentKnowledge) else DevelopmentKnowledge.model_validate(item))
            except Exception:
                continue
            if len(result) == 5: break
        return result

    def _bind(self, profile: NamingSqlProfile, spec: DataAccessSpec, knowledge: list[DevelopmentKnowledge]) -> ParamBindingPlan:
        aliases: dict[str, set[str]] = {}
        for entry in knowledge:
            try:
                items = entry.param_aliases.items()
            except Exception:
                continue
            for name, values in items:
                nk = _key(name)
                if not nk or not isinstance(values, list): continue
                aliases.setdefault(nk, set()).update(_key(x) for x in values[:50] if _key(x))
        bindings, unbound, ambiguous = [], [], []
        for param in profile.params:
            pk = _key(param.name)
            scored: list[tuple[float, Any, str]] = []
            for value in spec.available_values:
                if param.is_list != value.is_list: continue
                if not _type_ok(param.data_type, value.data_type): continue
                vk = _key(value.name)
                if pk and pk == vk: scored.append((1.0, value, "exact normalized name")); continue
                if vk and vk in aliases.get(pk, set()): scored.append((.95, value, "development alias")); continue
                param_tags = _tokens(param.name) - _GENERIC_SEMANTIC
                value_tags = (_tokens(value.name) | _tokens(" ".join(value.semantic_tags))) - _GENERIC_SEMANTIC
                if param_tags.intersection(value_tags) and _type_family(param.data_type) and _type_family(param.data_type) == _type_family(value.data_type):
                    scored.append((.85, value, "semantic tag and type"))
            if not scored:
                unbound.append(_compact(param.name)); continue
            best = max(x[0] for x in scored); winners = [x for x in scored if x[0] == best]
            if len(winners) != 1:
                ambiguous.append(_compact(param.name)); continue
            confidence, value, reason = winners[0]
            bindings.append(ParamBinding(param_name=_compact(param.name), source_ref=_compact(value.source_ref), confidence=confidence, reason=reason))
        return ParamBindingPlan(bindings=bindings, unbound_params=unbound, ambiguous_params=ambiguous,
                                is_complete=not unbound and not ambiguous and len(bindings) == len(profile.params))

    def select(self, request: NamingSqlSelectionRequest, loaded_resource: Any,
               data_access_spec: DataAccessSpec | None = None) -> NamingSqlSelectionResult:
        knowledge = self._knowledge(request)
        if data_access_spec is None:
            spec = (self._spec_generator or DataAccessSpecGenerator()).generate(request, knowledge=knowledge)
        else:
            spec = data_access_spec.model_copy(deep=True)
        resolution = self._bo_resolver.resolve(explicit_bo=request.bo_name, spec=spec,
            bo_registry=loaded_resource.bo_registry, profiles=loaded_resource.naming_sql_profiles)
        profiles = []
        for key, values in loaded_resource.naming_sql_profiles.items():
            bo = loaded_resource.bo_registry.get(key)
            if bo is None or bo.bo_name != resolution.bo_name: continue
            profiles.extend(p for p in values if p.site_id == request.site_id and p.bo_name == resolution.bo_name)
        rejected, fallbacks, survivors = [], [], []
        recommended = {_key(x) for k in knowledge for x in k.naming_sql_names if _key(x)}
        requirements = [_canonical_requirement(x) for x in spec.filter_requirements if _canonical_requirement(x)]
        scoped_profiles = [p for p in profiles if not p.is_full_table]
        recalled = self._candidate_retriever.retrieve(spec=spec.model_copy(deep=True), profiles=list(scoped_profiles), knowledge=list(knowledge), limit=30)
        loaded_by_key = {(p.naming_sql_id, p.sql_name): p for p in scoped_profiles}
        recalled_keys = list(dict.fromkeys((p.naming_sql_id, p.sql_name) for p in recalled[:30] if isinstance(p, NamingSqlProfile)))
        candidates = [loaded_by_key[key] for key in recalled_keys if key in loaded_by_key] + [p for p in profiles if p.is_full_table]
        alias_pairs: set[tuple[str, str]] = set()
        for item in knowledge:
            try: alias_items = item.param_aliases.items()
            except Exception: continue
            for name, aliases in alias_items:
                if not isinstance(aliases, list): continue
                for alias in aliases[:50]:
                    pair = (_key(name), _key(alias))
                    if pair[0] and pair[1]: alias_pairs.add(pair)
        for profile in candidates:
            plan = self._bind(profile, spec, knowledge)
            codes = []
            if plan.unbound_params: codes.append("PARAM_UNBOUND")
            if plan.ambiguous_params: codes.append("PARAM_AMBIGUOUS")
            searchable_filters = {_key(x) for x in (*profile.filter_fields, *(p.name for p in profile.params)) if _key(x)}
            def covered(req: str) -> bool:
                return req in searchable_filters or any((item, req) in alias_pairs or (req, item) in alias_pairs for item in searchable_filters)
            if not all(covered(req) for req in requirements): codes.append("FILTER_NOT_COVERED")
            if profile.is_full_table:
                binding_codes = [code for code in codes if code.startswith("PARAM_")]
                if binding_codes: rejected.append(RejectedNamingSql(naming_sql_id=profile.naming_sql_id, sql_name=profile.sql_name, reject_codes=binding_codes))
                else: fallbacks.append((profile, plan))
                continue
            text = " ".join((profile.sql_name, profile.label_name, profile.sql_description, profile.search_text, *profile.scope_tags))
            explicit = _key(profile.sql_name) in _key(request.query) or _key(profile.sql_name) in recommended
            coverage = 1.0 if not requirements else sum(covered(r) for r in requirements) / len(requirements)
            avg = sum(x.confidence for x in plan.bindings) / len(plan.bindings) if plan.bindings else 0.0
            business = _tokens(" ".join((*spec.business_terms, *spec.scope_terms)))
            overlap = min(len(business.intersection(_tokens(text))) / max(len(business), 1), 1)
            query_tokens = _tokens(request.query); text_overlap = min(len(query_tokens.intersection(_tokens(text))) / max(len(query_tokens), 1), 1)
            score = min(100.0, (40 if explicit else 0) + 25*coverage + 20*avg + 10*overlap + 5*text_overlap)
            if score <= 0: codes.append("LOW_RELEVANCE")
            if codes: rejected.append(RejectedNamingSql(naming_sql_id=profile.naming_sql_id, sql_name=profile.sql_name, reject_codes=codes))
            else: survivors.append(SelectedNamingSql(naming_sql_id=profile.naming_sql_id, sql_name=profile.sql_name, score=score, binding_plan=plan, reasons=["deterministic relevance score"]))
        survivors.sort(key=lambda x: (-x.score, x.sql_name, x.naming_sql_id)); fallbacks.sort(key=lambda x: (x[0].sql_name, x[0].naming_sql_id)); rejected.sort(key=lambda x: (x.sql_name, x.naming_sql_id))
        chosen, mode = None, "deterministic_fallback"
        if survivors:
            chosen, mode = survivors[0], "not_required"
            if len(survivors) > 1:
                mode = "deterministic_fallback"; top = survivors[:5]; allowed = {x.naming_sql_id: x for x in top}
                if self._reviewer:
                    try:
                        reply = self._reviewer.review(spec=spec.model_copy(deep=True), candidates=[NamingSqlReviewCandidate(naming_sql_id=x.naming_sql_id, sql_name=x.sql_name, score=x.score, reasons=list(x.reasons)) for x in top])
                    except Exception: reply = None
                    if isinstance(reply, str) and reply in allowed: chosen, mode = allowed[reply], "llm"
        elif spec.allow_full_table and fallbacks:
            profile, plan = fallbacks.pop(0); chosen = SelectedNamingSql(naming_sql_id=profile.naming_sql_id, sql_name=profile.sql_name, score=0.0, binding_plan=plan, reasons=["full table explicitly allowed"])
        fallback_models = [FallbackNamingSql(naming_sql_id=p.naming_sql_id, sql_name=p.sql_name) for p, _ in fallbacks]
        return NamingSqlSelectionResult(status="selected" if chosen else "needs_review", selected_bo=resolution.bo_name,
            selected=chosen.model_copy(deep=True) if chosen else None, fallback_candidates=fallback_models,
            rejected_candidates=rejected, review_mode=mode)
