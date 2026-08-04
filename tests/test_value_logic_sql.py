from agent.environment.environment import FilteredEnvironment
from agent.resource_manager.loader.registry_models import BoRegistry
from agent.value_logic_sql import SqlBranchBoSelector, SqlBranchResolver, SqlParamBinder
from agent.resource_manager.loader.resource_loader import ResourceLoader
from tests.test_environment import StaticResourceLoader, bill_statement_context_payload, sample_edsl_tree_payload
from tests.test_resource_loader import sample_bo_payload


class FirstProfileSelector:
    def select(self, **request):
        return request["profiles"][:1]


def test_sql_bo_selector_matches_generated_keywords_against_bo_names():
    calls = []

    def decide(**kwargs):
        calls.append(kwargs)
        if kwargs["prompt_template"] == "value_logic_sql_bo_keywords":
            return {"bo_keywords": ["transaction", "bt"]}
        assert "BB_BAK_TRANS" in kwargs["bo_candidates_json"]
        assert "CUSTOMER_ACCOUNT" not in kwargs["bo_candidates_json"]
        return {"bo_name": "BB_BAK_TRANS"}

    loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
    bo_registry = {
        **loaded.bo_registry,
        "CUSTOMER_ACCOUNT": BoRegistry(
            resource_id="bo.customer",
            bo_name="CUSTOMER_ACCOUNT",
            bo_desc="customer account",
            property_list=[],
            naming_sql_list=[],
        ),
    }
    selected = SqlBranchBoSelector(decision_fn=decide).select(
        query="query transaction list",
        node={"node_id": "ab", "tree_node_type": "parent_list"},
        bo_registry=bo_registry,
        context_pack=None,
    )

    assert selected == "BB_BAK_TRANS"
    assert [call["prompt_template"] for call in calls] == [
        "value_logic_sql_bo_keywords",
        "value_logic_sql_bo_selector",
    ]


def test_sql_bo_selector_returns_none_when_keywords_do_not_match_bo_name():
    def decide(**kwargs):
        return {"bo_keywords": ["missing customer"]}

    loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
    selected = SqlBranchBoSelector(decision_fn=decide).select(
        query="query transaction list",
        node={"node_id": "ab", "tree_node_type": "parent_list"},
        bo_registry=loaded.bo_registry,
        context_pack=None,
    )

    assert selected is None


def test_sql_param_binding_context_filter_exposes_matching_param_context():
    payload = bill_statement_context_payload()
    payload["bo"] = sample_bo_payload()
    loaded = StaticResourceLoader(payload).load_resource("site1", "project1", sample_edsl_tree_payload())
    calls = []

    def bind_params(**kwargs):
        calls.append(kwargs)
        return [
            {
                "param_name": "END_DATE",
                "param_value": "$ctx$.billStatement.END_DATE",
            }
        ]

    result = SqlBranchResolver(
        bo_selector=lambda **kwargs: "BB_BAK_TRANS",
        naming_sql_selector_factory=lambda: FirstProfileSelector(),
        param_binder=bind_params,
    ).resolve(
        query="query transaction list by end date",
        node={"node_id": "ab", "tree_node_type": "parent_list"},
        loaded_resource=loaded,
        node_path="$.mapping_content.children[1]",
        context_pack=None,
    )

    assert result.logic_type == "sql"
    assert result.source.sql_params[0] == {
        "param_name": "END_DATE",
        "param_value": "$ctx$.billStatement.END_DATE",
    }
    assert "$ctx$.billStatement.END_DATE" in calls[0]["available_context_json"]


def test_sql_param_binder_accepts_sql_condition_param_shape():
    payload = bill_statement_context_payload()
    payload["bo"] = sample_bo_payload()
    loaded = StaticResourceLoader(payload).load_resource("site1", "project1", sample_edsl_tree_payload())
    end_date = loaded.context_registry["$ctx$.billStatement.END_DATE"]
    sql_def = loaded.bo_registry["BB_BAK_TRANS"].naming_sql_list[0]

    def decide(**kwargs):
        return {
            "sql_condition": [
                {
                    "param_name": "END_DATE",
                    "param_value": "$ctx$.billStatement.END_DATE",
                }
            ]
        }

    bindings = SqlParamBinder(decision_fn=decide).bind(
        query="query by end date",
        node={"node_id": "ab"},
        sql_name=sql_def.sql_name,
        params=sql_def.param_list,
        filtered_env=FilteredEnvironment(selected_global_contexts=[end_date]),
    )

    assert bindings[0] == {
        "param_name": "END_DATE",
        "param_value": "$ctx$.billStatement.END_DATE",
    }
    assert len(bindings) == len(sql_def.param_list)
