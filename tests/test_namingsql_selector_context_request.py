from copy import deepcopy
import pytest
from pydantic import ValidationError

from agent.context_manager.errors import ContextBuildError
from agent.context_manager.models import (
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
    NamingSqlSelector,
)


class CapturingManager:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def build_context(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


def _request(**updates):
    values = dict(site_id="site", project_id="project", query="find fees",
                  node={"id": "n"}, json_path="$.nodes[0]",
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


def test_select_builds_exact_context_request_and_calls_manager_once():
    manager = CapturingManager(_context())
    response = NamingSqlSelector(manager).select(_request())

    assert response.success is True
    assert len(manager.calls) == 1
    args, kwargs = manager.calls[0]
    assert kwargs == {}
    assert len(args) == 1
    assert args[0].model_dump() == {
        "site_id": "site", "project_id": "project", "chain_type": "namingsql_selection",
        "query": "find fees", "node": {"id": "n"}, "json_path": "$.nodes[0]",
        "target_bo_name": "Fee", "parent_bo_hint": "Account",
        "target_logic_area_id_list": ["la-1"], "max_context_items": 50,
        "top_k": 7, "debug": False,
    }


def test_success_maps_final_context_and_deep_copies_it():
    context = _context(prompt_view={"internal": ["secret"]})
    response = NamingSqlSelector(CapturingManager(context)).select(_request(debug=True))
    snapshot = deepcopy(response.model_dump())
    context.resource_candidates.candidates[0].bo_name = "mutated"
    context.requirement_hints[0].semantic_name = "mutated"
    context.constraints.allowed_bo_names.append("mutated")
    context.prompt_view["internal"].append("mutated")
    assert response.model_dump() == snapshot
    assert response.prompt_view == {"internal": ["secret"]}
    assert response.context_requirements_hint[0].semantic_name == "account_id"
    assert response.selection_constraints.allowed_bo_names == ["Fee"]


def test_prompt_view_is_debug_gated():
    context = _context(prompt_view={"internal": "secret"})
    assert NamingSqlSelector(CapturingManager(context)).select(_request()).prompt_view is None


@pytest.mark.parametrize("code", [
    "AI_CONFIGURATION_REQUIRED", "EMBEDDING_FAILED", "LLM_RERANK_FAILED",
    "LLM_ORGANIZER_FAILED", "INVALID_LLM_OUTPUT", "RULE_FILE_MISSING",
    "EDSL_NODE_NOT_FOUND", "UNSUPPORTED_CONTEXT_CHAIN", "NO_NAMING_SQL_CANDIDATES",
])
def test_context_build_errors_become_stable_failures(code):
    response = NamingSqlSelector(CapturingManager(error=ContextBuildError(code, "private detail"))).select(
        _request(debug=True))
    assert response == NamingSqlSelectResponse(success=False, failure_reason=code)


def test_unexpected_errors_propagate():
    with pytest.raises(RuntimeError, match="boom"):
        NamingSqlSelector(CapturingManager(error=RuntimeError("boom"))).select(_request())


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
