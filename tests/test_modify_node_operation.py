import pytest

from agent.generate_node_operation import OperationFailure
from agent.modify_node_operation import (
    ExistingExpressionAdapter,
    MigrationPlanner,
    ModifyNodeOperation,
    ModifyNodeOperationInput,
    ModifyAdapterContext,
    ModifyIntentRouter,
    ModifyExecutor,
    ModifyPlanGenerator,
    NodeResolver,
)
from models import TreeNodeTerm
from agent.models import ValueLogicResult, ValueLogicSource


@pytest.fixture
def sample_tree():
    return {
        "mapping_content": {
            "tree_node_type": "parent",
            "node_id": "root-id",
            "xml_name_property": {"xml_name": "ROOT"},
            "local_context": [{"property_name": "rootValue"}],
            "children": [
                {
                    "tree_node_type": "simple_leaf",
                    "node_id": "leaf-id",
                    "xml_name_property": {"xml_name": "AMOUNT"},
                    "annotation": "old amount",
                    "data_expression": {"expression": "$ctx$.old"},
                    "data_type_config": {"data_type": "simple_string"},
                    "support_big_cust_acct": {},
                },
                {
                    "tree_node_type": "parent_list",
                    "node_id": "list-id",
                    "xml_name_property": {"xml_name": "DETAILS"},
                    "children": [],
                    "local_context": [{"property_name": "localValue"}],
                    "iter_local_context": [{"property_name": "itemValue"}],
                    "data_source": {},
                    "support_big_cust_acct": {},
                },
            ],
        }
    }


def test_resolves_target_parent_ancestors_and_pointer(sample_tree):
    result = NodeResolver().resolve(sample_tree, "$.mapping_content.children[1]")

    assert result.current_node["xml_name_property"]["xml_name"] == "DETAILS"
    assert result.parent_node["tree_node_type"] == "parent"
    assert result.node_pointer == "/mapping_content/children/1"
    assert result.ancestor_nodes[0]["tree_node_type"] == "parent"


def test_resolver_collects_visible_context(sample_tree):
    result = NodeResolver().resolve(sample_tree, "$.mapping_content.children[1]")

    assert [item["property_name"] for item in result.visible_local_context] == [
        "rootValue",
        "localValue",
        "itemValue",
    ]


def test_missing_target_uses_target_node_error(sample_tree):
    with pytest.raises(OperationFailure) as error:
        NodeResolver().resolve(sample_tree, "$.mapping_content.children[9]")

    assert error.value.code == "TARGET_NODE_NOT_FOUND"


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("把 XML 名称改成 ACCT_ID 并修改注释", "set_common_field"),
        ("修改取值表达式", "modify_expression"),
        ("改成金额类型，精度 2", "modify_datatype"),
        ("修改循环数据源", "modify_data_source"),
        ("修改 local context", "modify_context"),
        ("修改透视表 group by", "modify_ab_content"),
        ("改成列表节点", "change_node_type"),
    ],
)
def test_routes_modify_intent(query, intent):
    assert ModifyIntentRouter().route(query).intent_type == intent


@pytest.mark.parametrize(
    ("query", "target"),
    [
        ("改成父节点", "parent"),
        ("改成普通字段", "simple_leaf"),
        ("改成列表节点", "parent_list"),
        ("改成透视表", "ab_pivot_table"),
        ("改成两级表", "ab_two_level_table"),
    ],
)
def test_type_change_intent_includes_target_type(query, target):
    assert ModifyIntentRouter().route(query).target_tree_node_type == target


def test_plan_extracts_common_updates():
    query = "XML 名称改成 ACCT_ID，注释改成账户ID"
    intent = ModifyIntentRouter().route(query)

    plan = ModifyPlanGenerator().generate(intent, query)

    assert plan.common_field_updates["xml_name_property"]["xml_name"] == "ACCT_ID"
    assert plan.common_field_updates["annotation"] == "账户ID"


def test_plan_records_expression_and_datatype_queries():
    expression_query = "把取值表达式改成 $ctx$.bill.amount"
    datatype_query = "改成金额类型，精度 2"

    expression_plan = ModifyPlanGenerator().generate(
        ModifyIntentRouter().route(expression_query), expression_query
    )
    datatype_plan = ModifyPlanGenerator().generate(
        ModifyIntentRouter().route(datatype_query), datatype_query
    )

    assert expression_plan.expression_update_query == expression_query
    assert datatype_plan.datatype_update_query == datatype_query


def test_migration_parent_to_parent_list_preserves_children(sample_tree):
    original = sample_tree["mapping_content"]
    plan = MigrationPlanner().plan(original, "parent_list")

    candidate, report = ModifyExecutor().migrate(original, plan, "改成列表节点")

    assert candidate["children"] == original["children"]
    assert candidate["local_context"] == original["local_context"]
    assert "data_source" in candidate
    assert "iter_local_context" in candidate
    assert report.children_action == "keep"


def test_migration_parent_list_to_parent_drops_list_fields(sample_tree):
    original = sample_tree["mapping_content"]["children"][1]
    plan = MigrationPlanner().plan(original, "parent")

    candidate, report = ModifyExecutor().migrate(
        original, plan, "删除列表数据源和迭代上下文，改成父节点"
    )

    validated = TreeNodeTerm.model_validate(candidate)
    assert validated.tree_node_type == "parent"
    assert validated.data_source is None
    assert validated.iter_local_context is None
    assert "data_source" in report.dropped_fields
    assert report.destructive_risk is True


def test_migration_simple_leaf_to_parent_initializes_container(sample_tree):
    original = sample_tree["mapping_content"]["children"][0]
    plan = MigrationPlanner().plan(original, "parent")

    candidate, report = ModifyExecutor().migrate(original, plan, "改成父节点")

    validated = TreeNodeTerm.model_validate(candidate)
    assert validated.tree_node_type == "parent"
    assert validated.children == []
    assert validated.local_context == []
    assert validated.data_expression is None


def test_migration_only_changes_node_id_when_rebuild_is_explicit(sample_tree):
    original = sample_tree["mapping_content"]["children"][0]
    plan = MigrationPlanner().plan(original, "parent")

    preserved, _ = ModifyExecutor().migrate(original, plan, "改成父节点")
    rebuilt, _ = ModifyExecutor().migrate(original, plan, "重建节点并改成父节点")

    assert preserved["node_id"] == "leaf-id"
    assert rebuilt["node_id"] != "leaf-id"


def test_migration_simple_leaf_to_pivot_initializes_matching_ab_content(sample_tree):
    original = sample_tree["mapping_content"]["children"][0]
    plan = MigrationPlanner().plan(original, "ab_pivot_table")

    candidate, report = ModifyExecutor().migrate(original, plan, "改成透视表")

    validated = TreeNodeTerm.model_validate(candidate)
    assert validated.ab_content.tree_node_type == "ab_pivot_table"


def test_migration_pivot_to_two_level_preserves_compatible_ab_fields():
    original = TreeNodeTerm(
        tree_node_type="ab_pivot_table",
        ab_content={"tree_node_type": "ab_pivot_table", "group_by_fields": []},
    ).model_dump(mode="json", exclude_none=True)
    plan = MigrationPlanner().plan(original, "ab_two_level_table")

    candidate, report = ModifyExecutor().migrate(original, plan, "改成两级表")

    validated = TreeNodeTerm.model_validate(candidate)
    assert validated.ab_content.tree_node_type == "ab_two_level_table"
    assert validated.ab_content.group_by_fields == []


def test_operation_modifies_xml_name_and_annotation(sample_tree):
    result = ModifyNodeOperation().execute(
        ModifyNodeOperationInput(
            query="XML 名称改成 ACCT_ID，注释改成账户ID",
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.original_node["xml_name_property"]["xml_name"] == "AMOUNT"
    assert result.modified_node["xml_name_property"]["xml_name"] == "ACCT_ID"
    assert result.modified_node["annotation"] == "账户ID"


def test_operation_modifies_leaf_datatype_to_money(sample_tree):
    result = ModifyNodeOperation().execute(
        ModifyNodeOperationInput(
            query="改成金额类型，精度 2",
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.modified_node["data_type_config"]["data_type"] == "money"
    assert result.modified_node["data_type_config"]["decimal_precision"] == "2"


def test_operation_modifies_expression_through_adapter(sample_tree):
    def expression_adapter(context):
        assert context.current_node["node_id"] == "leaf-id"
        return {"expression_type": "edsl_expression", "expression": "$ctx$.new"}

    result = ModifyNodeOperation(expression_adapter=expression_adapter).execute(
        ModifyNodeOperationInput(
            query="覆盖取值表达式为 $ctx$.new",
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
            allow_destructive=True,
        )
    )

    assert result.success is True
    assert result.modified_node["data_expression"]["expression"] == "$ctx$.new"
    assert result.migration_report["destructive_risk"] is True


def test_expression_adapter_failure_is_structured(sample_tree):
    def failing_adapter(context):
        raise RuntimeError("generator unavailable")

    result = ModifyNodeOperation(expression_adapter=failing_adapter).execute(
        ModifyNodeOperationInput(
            query="覆盖取值表达式",
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
            allow_destructive=True,
        )
    )

    assert result.success is False
    assert result.failure_reason == "EXPRESSION_GENERATION_FAILED"
    assert result.patch_list == []


def test_existing_expression_adapter_reuses_value_logic_generator(sample_tree):
    class FakeValueLogicGenerator:
        def __init__(self):
            self.request = None

        def generate(self, request):
            self.request = request
            return ValueLogicResult(
                node_id="leaf-id",
                logic_type="expression",
                expression="$ctx$.generated",
                source=ValueLogicSource(source_type="plan"),
            )

    generator = FakeValueLogicGenerator()
    adapter = ExistingExpressionAdapter(generator=generator)
    context = ModifyAdapterContext(
        query="修改表达式",
        node_path="$.mapping_content.children[0]",
        current_node=sample_tree["mapping_content"]["children"][0],
        parent_node=sample_tree["mapping_content"],
        edsl_tree=sample_tree,
        site_id="site-1",
        project_id="project-1",
    )

    result = adapter(context)

    assert result.expression == "$ctx$.generated"
    assert generator.request.edsl_tree == sample_tree
    assert generator.request.node_path == "$.mapping_content.children[0]"


def test_parent_with_children_cannot_become_leaf_without_authorization(sample_tree):
    result = ModifyNodeOperation().execute(
        ModifyNodeOperationInput(
            query="改成普通字段",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is False
    assert result.failure_reason == "DESTRUCTIVE_CHANGE_NOT_ALLOWED"
    assert result.patch_list == []


def test_authorized_clear_allows_parent_to_leaf(sample_tree):
    result = ModifyNodeOperation().execute(
        ModifyNodeOperationInput(
            query="删除并清空子节点，改成普通字段",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
            allow_destructive=True,
        )
    )

    assert result.success is True
    assert result.modified_node["tree_node_type"] == "simple_leaf"
    assert result.migration_report["children_action"] == "drop"
    assert result.migration_report["original_children_count"] == 2


def test_authorized_parent_list_to_parent_reports_dropped_fields(sample_tree):
    result = ModifyNodeOperation().execute(
        ModifyNodeOperationInput(
            query="删除数据源和迭代上下文，改成父节点",
            node_path="$.mapping_content.children[1]",
            edsl_tree=sample_tree,
            allow_destructive=True,
        )
    )

    assert result.success is True
    assert result.modified_node["tree_node_type"] == "parent"
    assert "data_source" in result.migration_report["dropped_fields"]
    assert "iter_local_context" not in result.modified_node


@pytest.mark.parametrize(
    ("query", "expected_type"),
    [("改成父节点", "parent"), ("改成透视表", "ab_pivot_table")],
)
def test_operation_migrates_simple_leaf_to_valid_target(sample_tree, query, expected_type):
    result = ModifyNodeOperation().execute(
        ModifyNodeOperationInput(
            query=query,
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    validated = TreeNodeTerm.model_validate(result.modified_node)
    assert validated.tree_node_type == expected_type


def test_success_returns_whole_node_replace_patch(sample_tree):
    result = ModifyNodeOperation().execute(
        ModifyNodeOperationInput(
            query="XML 名称改成 ACCT_ID",
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
        )
    )

    assert result.patch_list == [
        {
            "op": "replace",
            "path": "/mapping_content/children/0",
            "value": result.modified_node,
        }
    ]


def test_valid_llm_intent_is_used(sample_tree):
    operation = ModifyNodeOperation(
        intent_llm=lambda query, current_node: {
            "intent_type": "set_common_field",
            "affected_fields": ["annotation"],
            "reason": "llm selected common update",
        }
    )

    result = operation.execute(
        ModifyNodeOperationInput(
            query="注释改成新注释",
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.modify_intent["reason"] == "llm selected common update"


def test_invalid_llm_intent_falls_back_to_local_router(sample_tree):
    operation = ModifyNodeOperation(
        intent_llm=lambda query, current_node: {"intent_type": "unknown"}
    )

    result = operation.execute(
        ModifyNodeOperationInput(
            query="注释改成新注释",
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.modify_intent["intent_type"] == "set_common_field"
