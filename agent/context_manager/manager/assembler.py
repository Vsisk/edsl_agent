from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.context_manager.errors import (ContextBuildError, INVALID_LLM_OUTPUT,
    LLM_ORGANIZER_FAILED, NO_NAMING_SQL_CANDIDATES)
from agent.context_manager.models import (BuildContextRequest, ContextEvidenceItem,
    ContextRequirementHint, NamingSqlContextRequestSummary, NamingSqlResourceCandidates,
    NamingSqlSelectionConstraints, NamingSqlSelectionContext, ReferenceCaseBlock)
from agent.context_manager.renderers import NamingSqlContextRenderer
from agent.llm.llm_client import LLMClient
from agent.llm.prompt_manager import PromptManager, prompt_manager


class JsonClient(Protocol):
    def complete_json(self, prompt: str) -> dict[str, Any]: ...


class OrganizerHint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    semantic_name: str
    expected_data_type: str | None = None
    expected_data_type_name: str | None = None
    source_hint: str | None = None
    bind_to_candidates: list[str] = Field(default_factory=list)
    candidate_context_paths: list[str] = Field(default_factory=list)
    evidence: list["OrganizerEvidence"] = Field(default_factory=list)


class OrganizerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str
    action: str
    asset_id: str | None = None
    evidence: str
    payload: dict[str, Any] = Field(default_factory=dict)


class OrganizerConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    allowed_bo_names: list[str] = Field(default_factory=list)
    allowed_naming_sql_aliases: list[str] = Field(default_factory=list)
    max_candidates: int | None = None


class OrganizerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selected_candidate_aliases: list[str]
    rejected_candidate_aliases: list[str] = Field(default_factory=list)
    requirement_hints: list[OrganizerHint] = Field(default_factory=list)
    constraints: OrganizerConstraints = Field(default_factory=OrganizerConstraints)
    retained_reference_aliases: list[str] = Field(default_factory=list)
    evidence_trace: list[OrganizerEvidence] = Field(default_factory=list)


class ContextPackAssembler:
    def __init__(self, client: JsonClient | None = None, prompt_manager: PromptManager | None = None,
                 renderer: NamingSqlContextRenderer | None = None, *, llm_client: JsonClient | None = None) -> None:
        self.client = client or llm_client or LLMClient()
        self.prompt_manager = prompt_manager or globals()["prompt_manager"]
        self.renderer = renderer or NamingSqlContextRenderer()

    def assemble(self, request: BuildContextRequest, global_context: Any, node_context: Any,
                 logic_area_context: Any, resource_candidates: NamingSqlResourceCandidates,
                 ootb_reference_cases: ReferenceCaseBlock, site_knowledge_cases: ReferenceCaseBlock) -> NamingSqlSelectionContext:
        item_budget = max(0, request.max_context_items)
        visible_candidates = list(resource_candidates.candidates[:item_budget])
        if not visible_candidates:
            raise ContextBuildError(NO_NAMING_SQL_CANDIDATES, "No NamingSQL candidates")
        candidates = {f"c{i:04d}": item for i, item in enumerate(visible_candidates)}
        remaining_budget = max(0, item_budget - len(candidates))
        refs = (list(ootb_reference_cases.candidates) + list(site_knowledge_cases.candidates))[:remaining_budget]
        references = {f"r{i:04d}": item for i, item in enumerate(refs)}
        try:
            context_json = self.renderer.render(request=request, global_context=global_context,
                node_context=node_context, logic_area_context=logic_area_context,
                resource_candidates=resource_candidates, ootb_reference_cases=ootb_reference_cases,
                site_knowledge_cases=site_knowledge_cases, candidate_aliases=candidates,
                reference_aliases=references)
            prompt = self.prompt_manager.render("context_namingsql_organizer", lang="zh",
                context_json=context_json, top_k=str(request.top_k))
        except Exception as exc:
            raise ContextBuildError(LLM_ORGANIZER_FAILED, "LLM organizer prompt preparation failed") from exc
        try:
            raw = self.client.complete_json(prompt)
        except Exception as exc:
            raise ContextBuildError(LLM_ORGANIZER_FAILED, "LLM organizer request failed") from exc
        try:
            output = OrganizerOutput.model_validate(raw)
            self._unique(output.selected_candidate_aliases)
            self._unique(output.rejected_candidate_aliases)
            self._unique(output.retained_reference_aliases)
            required_count = min(request.top_k, len(candidates))
            if len(output.selected_candidate_aliases) != required_count:
                raise ValueError("organizer must select the exact requested candidate count")
            if set(output.selected_candidate_aliases) & set(output.rejected_candidate_aliases):
                raise ValueError("selected and rejected candidates overlap")
            if any(alias not in candidates for alias in output.selected_candidate_aliases + output.rejected_candidate_aliases):
                raise ValueError("unknown candidate alias")
            if any(alias not in references for alias in output.retained_reference_aliases):
                raise ValueError("unknown reference alias")
            self._unique(output.constraints.allowed_bo_names)
            self._unique(output.constraints.allowed_naming_sql_aliases)
            visible_bo_names = {item.bo_name for item in candidates.values()}
            if any(name not in visible_bo_names for name in output.constraints.allowed_bo_names):
                raise ValueError("unknown BO constraint")
            if any(alias not in candidates for alias in output.constraints.allowed_naming_sql_aliases):
                raise ValueError("unknown NamingSQL constraint alias")
            if output.constraints.max_candidates is not None and (
                output.constraints.max_candidates <= 0 or
                output.constraints.max_candidates > request.top_k or
                output.constraints.max_candidates != required_count
            ):
                raise ValueError("inconsistent max candidate constraint")
            allowed_hint_refs = set(candidates) | set(references)
            for hint in output.requirement_hints:
                if any(alias not in allowed_hint_refs for alias in hint.bind_to_candidates):
                    raise ValueError("unknown hint alias")
            if any(event.asset_id is not None and event.asset_id not in allowed_hint_refs
                   for event in output.evidence_trace):
                raise ValueError("unknown evidence alias")
        except (ValidationError, ValueError, TypeError) as exc:
            raise ContextBuildError(INVALID_LLM_OUTPUT, "LLM organizer output violates contract") from exc
        selected = [candidates[alias].model_copy(update={"rank": rank})
                    for rank, alias in enumerate(output.selected_candidate_aliases, 1)]
        canonical_hints = [ContextRequirementHint.model_validate(hint.model_dump()).model_copy(update={"bind_to_candidates": [
            candidates[a].candidate_id if a in candidates else references[a].asset.asset_id
            for a in hint.bind_to_candidates]}) for hint in output.requirement_hints]
        canonical_evidence = [ContextEvidenceItem.model_validate(event.model_dump()).model_copy(update={"asset_id": (
            candidates[event.asset_id].candidate_id if event.asset_id in candidates else references[event.asset_id].asset.asset_id
        )}) if event.asset_id is not None else event for event in output.evidence_trace]
        retained = set(output.retained_reference_aliases)
        ootb = self._retained_block(ootb_reference_cases, references, retained)
        site = self._retained_block(site_knowledge_cases, references, retained)
        evidence = list(global_context.evidence) + list(node_context.evidence)
        if logic_area_context is not None: evidence += list(logic_area_context.evidence)
        evidence += list(resource_candidates.evidence) + list(ootb.evidence_trace) + list(site.evidence_trace) + canonical_evidence
        result = NamingSqlSelectionContext(request=NamingSqlContextRequestSummary(**request.model_dump(exclude={"node", "max_context_items", "debug"})),
            global_context=global_context, node_context=node_context, logic_area_context=logic_area_context,
            resource_candidates=NamingSqlResourceCandidates(candidates=selected, evidence=resource_candidates.evidence),
            ootb_reference_cases=ootb, site_knowledge_cases=site, requirement_hints=canonical_hints,
            constraints=NamingSqlSelectionConstraints(
                allowed_bo_names=output.constraints.allowed_bo_names,
                allowed_naming_sql_ids=[candidates[a].naming_sql_id for a in output.constraints.allowed_naming_sql_aliases],
                max_candidates=len(selected)), evidence_trace=evidence,
            prompt_view={"prompt": prompt, "context_json": context_json, "raw_output": raw} if request.debug else None)
        return result

    @staticmethod
    def _unique(items: list[str]) -> None:
        if len(items) != len(set(items)): raise ValueError("duplicate aliases")

    @staticmethod
    def _retained_block(block: ReferenceCaseBlock, aliases: dict[str, Any], retained: set[str]) -> ReferenceCaseBlock:
        keep_ids = {id(aliases[a]) for a in retained}
        return block.model_copy(update={"candidates": [item for item in block.candidates if id(item) in keep_ids]})
