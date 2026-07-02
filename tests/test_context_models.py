import pytest
from pydantic import ValidationError

from agent.context_manager.models import BuildContextRequest, NamingSqlCandidate


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
