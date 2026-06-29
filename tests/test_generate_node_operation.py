import pytest

from agent.generate_node_operation import (
    CommonFieldGenerator,
    GenerateNodeOperation,
    GenerateNodeOperationInput,
    NodeTypeRouter,
    NodeContentIntentGenerator,
    NodeContentIntent,
    OperationFailure,
    PathResolver,
    TypeSpecificFieldGenerator,
)
from models import PivotTableTerm, TwoLevelTableTerm


@pytest.fixture(autouse=True)
def fake_generate_semantic_llm(monkeypatch):
    def fake_generate(prompt_key, **variables):
        query = variables.get("query", "")
        if prompt_key == "node_type_route_prompt":
            if "两级" in query:
                node_type = "ab_two_level_table"
            elif "透视" in query:
                node_type = "ab_pivot_table"
            elif "列表" in query or "循环" in query:
                node_type = "parent_list"
            elif "父节点" in query:
                node_type = "parent"
            else:
                node_type = "simple_leaf"
            return {"tree_node_type": node_type, "confidence": 1.0, "reason": "fake semantic", "evidence_terms": []}
        if prompt_key == "common_node_field_prompt":
            if not query:
                xml_name = ""
            elif "账户ID" in query:
                xml_name = "ACCT_ID"
            elif "账户信息" in query:
                xml_name = "ACCT_INFO"
            elif "账单明细" in query:
                xml_name = "BILL_DETAIL_LIST"
            elif "费用" in query:
                xml_name = "FEE_PIVOT"
            elif "两级" in query:
                xml_name = "TWO_LEVEL_DETAIL"
            else:
                xml_name = "ACCT"
            empty_type = "half" if "半标签" in query else "full" if "全标签" in query else "none"
            ids = [value for value in ("area-100", "area_200") if value in query]
            return {
                "xml_name_property": {"xml_name": xml_name, "xml_empty_field_type": empty_type},
                "annotation": query,
                "reference_logic_area_id_list": ids,
            }
        if prompt_key == "node_content_intent_prompt":
            data_type = "money" if "金额" in query else "time" if "时间" in query else "simple_string"
            return {
                "tree_node_type": variables["tree_node_type"],
                "data_type": data_type,
                "requires_expression_generation": False,
                "requires_data_source_generation": False,
                "reason": "fake semantic",
            }
        raise AssertionError(prompt_key)

    monkeypatch.setattr("agent.generate_node_operation.generate_by_llm", fake_generate)


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
    fields = TypeSpecificFieldGenerator().generate(
        "simple_leaf",
        NodeContentIntent(tree_node_type="simple_leaf", data_type=expected),
    )

    assert fields["data_type_config"].data_type == expected
    assert "data_expression" in fields
    assert "support_big_cust_acct" in fields


def test_type_specific_parent_initializes_container_fields():
    fields = TypeSpecificFieldGenerator().generate(
        "parent", NodeContentIntent(tree_node_type="parent")
    )

    assert fields == {"children": [], "local_context": []}


def test_type_specific_parent_list_initializes_list_fields():
    fields = TypeSpecificFieldGenerator().generate(
        "parent_list", NodeContentIntent(tree_node_type="parent_list")
    )

    assert fields["children"] == []
    assert fields["local_context"] == []
    assert fields["iter_local_context"] == []
    assert "data_source" in fields
    assert "support_big_cust_acct" in fields


def test_type_specific_ab_nodes_create_matching_content_models():
    pivot = TypeSpecificFieldGenerator().generate(
        "ab_pivot_table", NodeContentIntent(tree_node_type="ab_pivot_table")
    )
    two_level = TypeSpecificFieldGenerator().generate(
        "ab_two_level_table", NodeContentIntent(tree_node_type="ab_two_level_table")
    )

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


def test_empty_query_fails_with_common_field_generation_error(sample_tree):
    result = GenerateNodeOperation().execute(
        GenerateNodeOperationInput(
            query="",
            node_path="$.mapping_content",
            edsl_tree=sample_tree,
        )
    )

    assert result.success is False
    assert result.failure_reason == "COMMON_FIELD_GENERATION_FAILED"
    assert result.patch is None


def test_invalid_llm_route_fails_without_local_fallback(sample_tree):
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

    assert result.success is False
    assert result.failure_reason == "NODE_TYPE_ROUTE_FAILED"


def test_llm_runtime_failure_fails_without_local_fallback(sample_tree):
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

    assert result.success is False
    assert result.failure_reason == "NODE_TYPE_ROUTE_FAILED"


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


def test_llm_router_uses_gateway_result_without_keyword_rules():
    router = NodeTypeRouter(
        llm_gateway=lambda query: {
            "tree_node_type": "parent_list",
            "confidence": 0.98,
            "reason": "semantic classification",
            "evidence_terms": ["semantic"],
        }
    )

    result = router.route("这句话不包含旧关键词")

    assert result.tree_node_type == "parent_list"
    assert result.source == "llm"


def test_llm_router_invalid_payload_fails_without_keyword_fallback():
    router = NodeTypeRouter(llm_gateway=lambda query: {"tree_node_type": "unknown"})

    with pytest.raises(OperationFailure) as error:
        router.route("生成列表节点")

    assert error.value.code == "NODE_TYPE_ROUTE_FAILED"


def test_llm_common_field_generator_uses_gateway_payload():
    generator = CommonFieldGenerator(
        llm_gateway=lambda query: {
            "xml_name_property": {"xml_name": "SEMANTIC_NAME", "xml_empty_field_type": "none"},
            "annotation": "from llm",
            "reference_logic_area_id_list": [],
        }
    )

    result = generator.generate("任意描述")

    assert result.xml_name_property.xml_name == "SEMANTIC_NAME"


def test_node_content_intent_generator_validates_llm_payload():
    generator = NodeContentIntentGenerator(
        llm_gateway=lambda query, tree_node_type: {
            "tree_node_type": tree_node_type,
            "data_type": "money",
            "requires_expression_generation": False,
            "requires_data_source_generation": False,
            "reason": "money semantics",
        }
    )

    result = generator.generate("任意金额语义", "simple_leaf")

    assert result.data_type == "money"


def test_default_generate_router_calls_generate_by_llm(monkeypatch):
    calls = []

    def fake_generate(prompt_key, **variables):
        calls.append((prompt_key, variables))
        return {
            "tree_node_type": "parent",
            "confidence": 1.0,
            "reason": "semantic",
            "evidence_terms": [],
        }

    monkeypatch.setattr("agent.generate_node_operation.generate_by_llm", fake_generate)

    NodeTypeRouter().route("任意语义")

    assert calls == [("node_type_route_prompt", {"query": "任意语义"})]
