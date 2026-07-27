import pytest
from pydantic import ValidationError

from agent.spec_orchestration.models import (
    CoverageDecision,
    CoverageKind,
    GoalRole,
    GoalStatus,
    ResourceTier,
    ValueGoal,
)
from agent.resource_manager.loader.registry_models import ReturnType


def test_value_goal_has_independent_mutable_defaults():
    first = ValueGoal(
        goal_id="root",
        semantic_name="客户名称",
        role=GoalRole.FINAL_OUTPUT,
        expected_type=ReturnType(data_type="basic", data_type_name="string", is_list=False),
    )
    second = ValueGoal(
        goal_id="other",
        semantic_name="客户ID",
        role=GoalRole.QUERY_PARAM,
        expected_type=ReturnType(data_type="basic", data_type_name="long", is_list=False),
    )

    first.depends_on.append("dependency")

    assert second.depends_on == []
    assert first.status == GoalStatus.PENDING
    assert first.current_tier == ResourceTier.VISIBLE_VALUE


def test_coverage_decision_rejects_selected_id_for_not_cover():
    with pytest.raises(ValidationError):
        CoverageDecision(
            kind=CoverageKind.NOT_COVER,
            selected_candidate_id="candidate-1",
            reason="not suitable",
        )


def test_coverage_decision_requires_selected_id_for_cover():
    with pytest.raises(ValidationError):
        CoverageDecision(kind=CoverageKind.DIRECT_COVER, reason="suitable")

