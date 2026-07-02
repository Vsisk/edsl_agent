import pytest
from pydantic import ValidationError

from agent.context_manager.errors import ContextBuildError
from agent.context_manager.models import (
    BuildContextRequest,
    ContextAsset,
    ContextEvidenceItem,
    GlobalContextBlock,
    NamingSqlCandidate,
    NamingSqlContextRequestSummary,
    NamingSqlResourceCandidates,
    NamingSqlSelectionContext,
    NodeContextBlock,
    ReferenceCaseBlock,
)


def test_build_context_request_defaults_chain_type_and_top_k():
    request = BuildContextRequest(
        site_id="s",
        project_id="p",
        query="fee",
        node={},
        json_path="$.nodes[0]",
    )

    assert request.chain_type == "namingsql_selection"
    assert request.top_k == 5


@pytest.mark.parametrize("top_k", [0, 21])
def test_build_context_request_rejects_top_k_outside_valid_range(top_k):
    with pytest.raises(ValidationError):
        BuildContextRequest(
            site_id="s",
            project_id="p",
            query="fee",
            node={},
            json_path="$.nodes[0]",
            top_k=top_k,
        )


def test_naming_sql_candidate_has_rank_and_no_score_field():
    candidate = NamingSqlCandidate(
        candidate_id="candidate-1",
        bo_name="Invoice",
        naming_sql_id="fee",
        source="resource_registry",
        rank=1,
    )

    assert candidate.rank == 1
    assert "score" not in NamingSqlCandidate.model_fields
    with pytest.raises(ValidationError):
        NamingSqlCandidate(
            candidate_id="candidate-1",
            bo_name="Invoice",
            naming_sql_id="fee",
            source="resource_registry",
            rank=1,
            score=0.9,
        )


def test_context_build_error_formats_optional_detail():
    without_detail = ContextBuildError("EMBEDDING_FAILED")
    with_detail = ContextBuildError("EMBEDDING_FAILED", "provider unavailable")

    assert without_detail.code == "EMBEDDING_FAILED"
    assert without_detail.detail == ""
    assert str(without_detail) == "EMBEDDING_FAILED"
    assert str(with_detail) == "EMBEDDING_FAILED: provider unavailable"


def test_context_asset_supports_optional_logic_area_id():
    asset = ContextAsset(
        asset_id="logic-area-1",
        asset_type="logic_area",
        scope="logic_area",
        logic_area_id="la-1",
        content={},
        index_text="Logic area",
    )

    assert asset.logic_area_id == "la-1"


def test_naming_sql_candidate_uses_structured_params_return_type_and_string_evidence():
    candidate = NamingSqlCandidate(
        candidate_id="candidate-1",
        bo_name="Invoice",
        naming_sql_id="fee",
        source="resource_registry",
        rank=1,
        param_list=[{"name": "invoiceId", "type": "string"}],
        return_type={"type": "number"},
        evidence=["matched annotation"],
    )

    assert candidate.param_list == [{"name": "invoiceId", "type": "string"}]
    assert candidate.return_type == {"type": "number"}
    assert candidate.evidence == ["matched annotation"]
    with pytest.raises(ValidationError):
        NamingSqlCandidate(
            candidate_id="candidate-1",
            bo_name="Invoice",
            naming_sql_id="fee",
            source="resource_registry",
            rank=1,
            param_list=["invoiceId"],
        )


def test_naming_sql_selection_context_prompt_view_is_a_dict():
    field = NamingSqlSelectionContext.model_fields["prompt_view"]

    assert field.annotation == dict | None


def _selection_context(**overrides):
    values = {
        "request": NamingSqlContextRequestSummary(
            site_id="s",
            project_id="p",
            query="fee",
            json_path="$.nodes[0]",
        ),
        "global_context": GlobalContextBlock(),
        "node_context": NodeContextBlock(json_path="$.nodes[0]", node={}),
        "resource_candidates": NamingSqlResourceCandidates(),
    }
    values.update(overrides)
    return NamingSqlSelectionContext(**values)


def test_aggregate_models_use_evidence_trace_with_independent_defaults():
    evidence = ContextEvidenceItem(
        source="resource_registry",
        action="loaded",
        evidence="resource exists",
    )
    reference = ReferenceCaseBlock(evidence_trace=[evidence])
    context = _selection_context(evidence_trace=[evidence])

    assert reference.evidence_trace == [evidence]
    assert context.evidence_trace == [evidence]

    first_reference = ReferenceCaseBlock()
    second_reference = ReferenceCaseBlock()
    first_reference.evidence_trace.append(evidence)
    assert second_reference.evidence_trace == []

    first_context = _selection_context()
    second_context = _selection_context()
    first_context.evidence_trace.append(evidence)
    assert second_context.evidence_trace == []


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ReferenceCaseBlock(unexpected=True),
        lambda: _selection_context(unexpected=True),
    ],
)
def test_aggregate_models_reject_extra_fields(factory):
    with pytest.raises(ValidationError):
        factory()
