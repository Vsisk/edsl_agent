from agent.resource_manager.loader.registry_models import ReturnType
from agent.spec_orchestration.models import (
    CoverageKind,
    GoalRole,
    ResourceCandidate,
    ResourceTier,
    ValueGoal,
)
from agent.spec_orchestration.semantic import SpecSemanticGateway


def _goal():
    return ValueGoal(
        goal_id="root",
        semantic_name="客户组名称",
        role=GoalRole.FINAL_OUTPUT,
        expected_type=ReturnType(
            data_type="basic", data_type_name="string", is_list=False
        ),
    )


def _candidate():
    return ResourceCandidate(
        candidate_id="ctx.cust_group_name",
        kind="context",
        resource={"path": "$ctx$.custGroup.name"},
        return_type=ReturnType(
            data_type="basic", data_type_name="string", is_list=False
        ),
    )


def test_generate_goal_keeps_code_authoritative_expected_type():
    def decide(**kwargs):
        assert kwargs["prompt_template"] == "spec_orchestrator_goal"
        return {
            "semantic_name": "客户组名称",
            "keywords": ["custGrpName"],
            "aliases": ["customer group name"],
            "target_bo_name": "BB_DIC_CUSTGRP",
            "target_field_name": "CUST_GRP_NAME",
        }

    gateway = SpecSemanticGateway(decision_fn=decide)
    goal = gateway.generate_goal(
        goal_id="root",
        node_info={"node_name": "客户组名称"},
        query="生成客户组名称",
        expected_type=ReturnType(
            data_type="basic", data_type_name="string", is_list=False
        ),
        role=GoalRole.FINAL_OUTPUT,
    )

    assert goal.expected_type.data_type_name == "string"
    assert goal.target_bo_name == "BB_DIC_CUSTGRP"


def test_request_and_context_pack_are_injected_as_prompt_background():
    calls = []

    def decide(**kwargs):
        calls.append(kwargs)
        return {"keywords": [], "aliases": [], "negative_keywords": []}

    gateway = SpecSemanticGateway(decision_fn=decide)
    gateway.configure_background(
        request={"site_id": "site-1", "query": "生成名称"},
        context_pack={"status": "complete", "current_node": {"node_id": "name"}},
    )

    gateway.generate_keywords(
        goal=_goal(),
        query="生成名称",
    )

    assert '"site_id":"site-1"' in calls[0]["request_json"]
    assert '"status":"complete"' in calls[0]["context_pack_json"]


def test_generate_keywords_ignores_model_resource_tier():
    def decide(**kwargs):
        assert kwargs["prompt_template"] == "spec_orchestrator_keywords"
        assert "resource_tier" not in kwargs
        return {
            "keywords": ["custGrpName"],
            "aliases": ["客户组名称"],
            "negative_keywords": [],
            "resource_tier": ResourceTier.FUNCTION.value,
        }

    result = SpecSemanticGateway(decision_fn=decide).generate_keywords(
        goal=_goal(),
        query="生成客户组名称",
    )

    assert result.keywords == ["custGrpName"]


def test_unknown_candidate_id_degrades_to_not_cover():
    def decide(**kwargs):
        assert kwargs["prompt_template"] == "spec_orchestrator_coverage"
        return {
            "kind": "direct_cover",
            "selected_candidate_id": "invented",
            "target_field_name": None,
            "missing_inputs": [],
            "continue_search": False,
            "reason": "looks right",
        }

    decision = SpecSemanticGateway(decision_fn=decide).decide_coverage(
        goal=_goal(),
        tier=ResourceTier.VISIBLE_VALUE,
        candidates=[_candidate()],
        query="生成客户组名称",
    )

    assert decision.kind == CoverageKind.NOT_COVER
    assert decision.continue_search is True


def test_invalid_coverage_payload_degrades_to_not_cover():
    gateway = SpecSemanticGateway(decision_fn=lambda **_: {"kind": "direct_cover"})

    decision = gateway.decide_coverage(
        goal=_goal(),
        tier=ResourceTier.VISIBLE_VALUE,
        candidates=[_candidate()],
        query="生成客户组名称",
    )

    assert decision.kind == CoverageKind.NOT_COVER
    assert decision.selected_candidate_id is None
