from agent.value_logic_sql import SqlBranchBoSelector
from tests.test_environment import sample_edsl_tree_payload
from agent.resource_manager.loader.resource_loader import ResourceLoader


def test_sql_bo_selector_uses_llm_prompt_and_accepts_known_bo_only():
    calls = []

    def decide(**kwargs):
        calls.append(kwargs)
        return {"bo_name": "BB_BAK_TRANS"}

    loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
    selected = SqlBranchBoSelector(decision_fn=decide).select(
        query="query transaction list",
        node={"node_id": "ab", "tree_node_type": "parent_list"},
        bo_registry=loaded.bo_registry,
        context_pack=None,
    )

    assert selected == "BB_BAK_TRANS"
    assert calls[0]["prompt_template"] == "value_logic_sql_bo_selector"
    assert "BB_BAK_TRANS" in calls[0]["bo_candidates_json"]


def test_sql_bo_selector_rejects_unknown_bo():
    def decide(**kwargs):
        return {"bo_name": "MISSING_BO"}

    loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
    selected = SqlBranchBoSelector(decision_fn=decide).select(
        query="query transaction list",
        node={"node_id": "ab", "tree_node_type": "parent_list"},
        bo_registry=loaded.bo_registry,
        context_pack=None,
    )

    assert selected is None
