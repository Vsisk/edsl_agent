import pytest

from agent.generate_node_operation import (
    CommonFieldGenerator,
    GenerateNodeOperation,
    GenerateNodeOperationInput,
    NodeTypeRouter,
    OperationFailure,
    PathResolver,
    TypeSpecificFieldGenerator,
)
from models import PivotTableTerm, TwoLevelTableTerm


@pytest.fixture
def sample_tree():
    return {
        "mapping_content": {
            "tree_node_type": "parent",
            "xml_name_property": {"xml_name": "ROOT"},
            "children": [
                {
                    "tree_node_type": "simple_leaf",
                    "xml_name_property": {"xml_name": "EXISTING"},
                },
                {
                    "tree_node_type": "parent_list",
                    "xml_name_property": {"xml_name": "DETAILS"},
                    "children": [],
                },
            ],
        }
    }


def test_resolves_parent_jsonpath_to_children_and_patch_paths(sample_tree):
    result = PathResolver().resolve(sample_tree, "$.mapping_content")

    assert result.parent_path == "$.mapping_content"
    assert result.children_path == "$.mapping_content.children"
    assert result.patch_path == "/mapping_content/children/-"


def test_normalizes_parent_path_without_root_marker(sample_tree):
    result = PathResolver().resolve(sample_tree, "mapping_content.children[1]")

    assert result.parent_path == "$.mapping_content.children[1]"
    assert result.patch_path == "/mapping_content/children/1/children/-"


def test_rejects_leaf_as_parent(sample_tree):
    with pytest.raises(OperationFailure) as error:
        PathResolver().resolve(sample_tree, "$.mapping_content.children[0]")

    assert error.value.code == "TARGET_PARENT_CANNOT_HAVE_CHILDREN"


def test_rejects_missing_parent(sample_tree):
    with pytest.raises(OperationFailure) as error:
        PathResolver().resolve(sample_tree, "$.mapping_content.children[9]")

    assert error.value.code == "TARGET_PARENT_NOT_FOUND"


@pytest.mark.parametrize(
    "node_path",
    ["", "$.mapping_content.children[*]", "$..children", "$.mapping_content.children[0:1]"],
)
def test_rejects_invalid_or_unsupported_parent_path(sample_tree, node_path):
    with pytest.raises(OperationFailure) as error:
        PathResolver().resolve(sample_tree, node_path)

    assert error.value.code == "INVALID_NODE_PATH"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("生成账户ID字段", "simple_leaf"),
        ("生成账户信息父节点", "parent"),
        ("生成账单明细列表节点", "parent_list"),
        ("生成费用透视表节点", "ab_pivot_table"),
        ("生成两级明细表节点", "ab_two_level_table"),
    ],
)
def test_routes_supported_node_types(query, expected):
    assert NodeTypeRouter().route(query).tree_node_type == expected


def test_two_level_route_takes_precedence_over_generic_detail_terms():
    route = NodeTypeRouter().route("生成summary/detail两级明细表")

    assert route.tree_node_type == "ab_two_level_table"


def test_common_fields_use_stable_xml_name_and_defaults():
    fields = CommonFieldGenerator().generate("生成账户ID字段")

    assert fields.xml_name_property.xml_name == "ACCT_ID"
    assert fields.xml_name_property.xml_empty_field_type == "none"
    assert fields.annotation == "生成账户ID字段"
    assert fields.reference_logic_area_id_list == []


@pytest.mark.parametrize(
    ("query", "expected"),
    [("生成账户字段，使用半标签", "half"), ("生成账户字段，使用全标签", "full")],
)
def test_common_fields_honor_explicit_xml_empty_field_mode(query, expected):
    fields = CommonFieldGenerator().generate(query)

    assert fields.xml_name_property.xml_empty_field_type == expected


def test_common_fields_extract_explicit_logic_area_ids():
    fields = CommonFieldGenerator().generate(
        "生成账户字段，logic area id: area-100，logic_area_id=area_200"
    )

    assert fields.reference_logic_area_id_list == ["area-100", "area_200"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("生成账户名称字段", "simple_string"),
        ("生成账单时间字段", "time"),
        ("生成账户金额字段", "money"),
    ],
)
def test_type_specific_simple_leaf_selects_data_type(query, expected):
    fields = TypeSpecificFieldGenerator().generate("simple_leaf", query)

    assert fields["data_type_config"].data_type == expected
    assert "data_expression" in fields
    assert "support_big_cust_acct" in fields


def test_type_specific_parent_initializes_container_fields():
    fields = TypeSpecificFieldGenerator().generate("parent", "生成账户父节点")

    assert fields == {"children": [], "local_context": []}


def test_type_specific_parent_list_initializes_list_fields():
    fields = TypeSpecificFieldGenerator().generate("parent_list", "生成账单明细列表")

    assert fields["children"] == []
    assert fields["local_context"] == []
    assert fields["iter_local_context"] == []
    assert "data_source" in fields
    assert "support_big_cust_acct" in fields


def test_type_specific_ab_nodes_create_matching_content_models():
    pivot = TypeSpecificFieldGenerator().generate("ab_pivot_table", "生成透视表")
    two_level = TypeSpecificFieldGenerator().generate("ab_two_level_table", "生成两级表")

    assert isinstance(pivot["ab_content"], PivotTableTerm)
    assert isinstance(two_level["ab_content"], TwoLevelTableTerm)


def test_generates_simple_leaf_and_add_patch(sample_tree):
    result = GenerateNodeOperation().execute(
        GenerateNodeOperationInput(
            query="生成账户ID字段",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.generated_node["tree_node_type"] == "simple_leaf"
    assert "data_expression" in result.generated_node
    assert "data_type_config" in result.generated_node
    assert "support_big_cust_acct" in result.generated_node
    assert result.patch == {
        "op": "add",
        "path": "/mapping_content/children/-",
        "value": result.generated_node,
    }


@pytest.mark.parametrize(
    ("query", "node_type", "expected_fields"),
    [
        ("生成账户信息父节点", "parent", {"children", "local_context"}),
        (
            "生成账单明细列表节点",
            "parent_list",
            {"data_source", "support_big_cust_acct", "children", "local_context", "iter_local_context"},
        ),
        ("生成费用透视表节点", "ab_pivot_table", {"ab_content"}),
        ("生成两级明细表节点", "ab_two_level_table", {"ab_content"}),
    ],
)
def test_generates_each_container_and_ab_node_type(
    sample_tree, query, node_type, expected_fields
):
    result = GenerateNodeOperation().execute(
        GenerateNodeOperationInput(
            query=query,
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.generated_node["tree_node_type"] == node_type
    assert expected_fields <= result.generated_node.keys()
    if node_type.startswith("ab_"):
        assert result.generated_node["ab_content"]["tree_node_type"] == node_type


def test_failure_never_returns_partial_patch(sample_tree):
    result = GenerateNodeOperation().execute(
        GenerateNodeOperationInput(
            query="生成账户字段",
            node_path="$.mapping_content.children[0]",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is False
    assert result.failure_reason == "TARGET_PARENT_CANNOT_HAVE_CHILDREN"
    assert result.generated_node is None
    assert result.patch is None
    assert result.validation_errors[0]["code"] == result.failure_reason


def test_empty_query_fails_with_xml_name_empty(sample_tree):
    result = GenerateNodeOperation().execute(
        GenerateNodeOperationInput(
            query="",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is False
    assert result.failure_reason == "XML_NAME_EMPTY"
    assert result.patch is None


def test_invalid_llm_route_falls_back_to_local_rules(sample_tree):
    operation = GenerateNodeOperation(
        route_llm=lambda query: {"tree_node_type": "unknown"}
    )

    result = operation.execute(
        GenerateNodeOperationInput(
            query="生成费用透视表节点",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.route_result["tree_node_type"] == "ab_pivot_table"
    assert result.route_result["source"] == "local"


def test_llm_runtime_failure_falls_back_to_local_rules(sample_tree):
    def unavailable_llm(query):
        raise RuntimeError("LLM unavailable")

    operation = GenerateNodeOperation(route_llm=unavailable_llm)

    result = operation.execute(
        GenerateNodeOperationInput(
            query="生成账单明细列表节点",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.route_result["tree_node_type"] == "parent_list"
    assert result.route_result["source"] == "local"


def test_local_route_failure_returns_structured_error(sample_tree):
    class FailingRouter:
        def route(self, query):
            raise RuntimeError("route failed")

    operation = GenerateNodeOperation(node_type_router=FailingRouter())

    result = operation.execute(
        GenerateNodeOperationInput(
            query="生成账户字段",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is False
    assert result.failure_reason == "NODE_TYPE_ROUTE_FAILED"
    assert result.patch is None


def test_valid_llm_common_fields_are_constrained_and_used(sample_tree):
    operation = GenerateNodeOperation(
        common_fields_llm=lambda query: {
            "xml_name_property": {
                "xml_name": "CUSTOM_ACCT",
                "xml_empty_field_type": "none",
            },
            "annotation": "custom annotation",
            "reference_logic_area_id_list": [],
            "children": ["not allowed"],
        }
    )

    result = operation.execute(
        GenerateNodeOperationInput(
            query="生成账户字段",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is True
    assert result.generated_node["xml_name_property"]["xml_name"] == "CUSTOM_ACCT"
    assert "children" not in result.generated_node
