import pytest
from pydantic import ValidationError

from agent.context_manager.models import (
    ContextEvidenceItem,
    ContextRequirementHint,
    GlobalContextBlock,
    NamingSqlCandidate,
    NamingSqlContextRequestSummary,
    NamingSqlResourceCandidates,
    NamingSqlSelectionConstraints,
    NamingSqlSelectionContext,
    NodeContextBlock,
)
from agent.naming_sql_selector import (
    NamingSqlSelectRequest,
    NamingSqlSelectResponse,
    SelectionMode,
)
from agent.context_pack.models import ContextPack


def _request(**updates):
    values = dict(site_id="site", project_id="project", query="find fees",
                  node={"id": "n"}, json_path="$.nodes[0]",
                  context_pack=ContextPack(status="complete", request_summary={"query": "find fees"},
                                           current_node={"id": "n"}),
                  target_bo_name="Fee", parent_bo_hint="Account",
                  target_logic_area_id_list=["la-1"], top_k=7, debug=False)
    values.update(updates)
    return NamingSqlSelectRequest(**values)


def _context(prompt_view=None):
    candidate = NamingSqlCandidate(candidate_id="c1", bo_name="Fee", naming_sql_id="sql1",
                                   source="resource_registry", rank=1)
    summary = NamingSqlContextRequestSummary(
        site_id="site", project_id="project", query="find fees", json_path="$.nodes[0]",
        target_bo_name="Fee", parent_bo_hint="Account",
        target_logic_area_id_list=["la-1"], top_k=7)
    hint = ContextRequirementHint(semantic_name="account_id")
    return NamingSqlSelectionContext(
        request=summary, global_context=GlobalContextBlock(),
        node_context=NodeContextBlock(json_path="$.nodes[0]", node={"id": "n"}),
        resource_candidates=NamingSqlResourceCandidates(candidates=[candidate]),
        requirement_hints=[hint],
        constraints=NamingSqlSelectionConstraints(allowed_bo_names=["Fee"]),
        evidence_trace=[], prompt_view=prompt_view)


@pytest.mark.parametrize("values", [
    {"success": True},
    {"success": True, "candidates": [_context().resource_candidates.candidates[0]],
     "failure_reason": "FAILED"},
    {"success": False},
    {"success": False, "failure_reason": "FAILED", "prompt_view": {"secret": True}},
])
def test_response_invariants(values):
    with pytest.raises(ValidationError):
        NamingSqlSelectResponse(**values)


def test_request_requires_context_pack():
    values = _request().model_dump()
    values.pop("context_pack")
    with pytest.raises(ValidationError):
        NamingSqlSelectRequest(**values)


def test_success_requires_selection_mode_and_failed_response_forbids_it():
    candidate = _context().resource_candidates.candidates[0]
    with pytest.raises(ValidationError):
        NamingSqlSelectResponse(success=True, candidates=[candidate])
    with pytest.raises(ValidationError):
        NamingSqlSelectResponse(
            success=False,
            failure_reason="FAILED",
            selection_mode="deterministic_fallback",
        )


def test_request_is_strict_and_top_k_is_bounded():
    with pytest.raises(ValidationError):
        _request(extra_field=True)
    with pytest.raises(ValidationError):
        _request(top_k=21)


@pytest.mark.parametrize("updates", [
    {"debug": 1},
    {"top_k": "7"},
])
def test_request_rejects_coercion(updates):
    with pytest.raises(ValidationError):
        _request(**updates)


def test_response_rejects_coercion():
    with pytest.raises(ValidationError):
        NamingSqlSelectResponse(success=1, candidates=_context().resource_candidates.candidates)


@pytest.mark.parametrize(("field", "value"), [
    ("candidates", [{
        "candidate_id": "c1", "bo_name": "Fee", "naming_sql_id": "sql1",
        "source": "resource_registry", "rank": "1",
    }]),
    ("context_requirements_hint", [{"semantic_name": 1}]),
    ("selection_constraints", {"max_candidates": "5"}),
    ("selection_constraints", {"allowed_bo_names": [True]}),
    ("evidence_trace", [{"source": 1, "action": "selected", "evidence": "match"}]),
])
def test_response_rejects_nested_domain_coercion(field, value):
    values = {
        "success": True,
        "selection_mode": SelectionMode.LLM,
        "candidates": _context().resource_candidates.candidates,
        field: value,
    }
    with pytest.raises(ValidationError):
        NamingSqlSelectResponse(**values)


@pytest.mark.parametrize("field", [
    "candidate", "hint", "constraint", "evidence",
])
def test_response_revalidates_mutated_domain_instances_strictly(field):
    candidate = _context().resource_candidates.candidates[0]
    hint = ContextRequirementHint(semantic_name="account_id")
    constraint = NamingSqlSelectionConstraints(max_candidates=5)
    evidence = ContextEvidenceItem(source="organizer", action="selected", evidence="match")
    if field == "candidate":
        candidate.rank = "1"
    elif field == "hint":
        hint.semantic_name = 1
    elif field == "constraint":
        constraint.max_candidates = "5"
    else:
        evidence.source = True

    with pytest.raises(ValidationError):
        NamingSqlSelectResponse(
            success=True,
            selection_mode=SelectionMode.LLM,
            candidates=[candidate],
            context_requirements_hint=[hint],
            selection_constraints=constraint,
            evidence_trace=[evidence],
        )


def test_response_copies_valid_domain_instances():
    candidate = _context().resource_candidates.candidates[0]
    hint = ContextRequirementHint(semantic_name="account_id")
    constraint = NamingSqlSelectionConstraints(max_candidates=5)
    evidence = ContextEvidenceItem(source="organizer", action="selected", evidence="match")

    response = NamingSqlSelectResponse(
        success=True,
        selection_mode=SelectionMode.LLM,
        candidates=[candidate],
        context_requirements_hint=[hint],
        selection_constraints=constraint,
        evidence_trace=[evidence],
    )

    assert response.candidates[0] is not candidate
    assert response.context_requirements_hint[0] is not hint
    assert response.selection_constraints is not constraint
    assert response.evidence_trace[0] is not evidence
