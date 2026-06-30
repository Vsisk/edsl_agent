from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent.generate_node_operation import GenerateNodeOperation
from agent.operation_orchestration.action_adapter import OperationActionAdapter
from agent.operation_orchestration.node_index import build_node_index
from models import CommonFieldTerm, SummaryField, TreeNodeTerm


class RecordingOperation:
    def __init__(self, result):
        self.result = result
        self.inputs = []

    def execute(self, operation_input):
        self.inputs.append(operation_input)
        return self.result


class RecordingLogicGenerator:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return self.result


def node_tree():
    return {
        "mapping_content": {
            "node_id": "root-node",
            "tree_node_type": "parent",
            "children": [
                {
                    "node_id": "leaf-1",
                    "tree_node_type": "simple_leaf",
                    "annotation": "keep",
                    "data_expression": {"expression_type": "edsl_expression", "expression": "old"},
                },
                {
                    "node_id": "list-1",
                    "tree_node_type": "parent_list",
                    "children": [
                        {"node_id": "leaf-2", "tree_node_type": "simple_leaf"},
                    ],
                },
            ],
        }
    }


def ab_tree_with_field(tree_node_type, slot, *, summary=False):
    tree = GenerateNodeOperation._serialize_node(
        TreeNodeTerm.model_validate(
            {
                "node_id": "ab-parent",
                "tree_node_type": tree_node_type,
                "xml_name_property": {"xml_name": "AB_TABLE"},
                "ab_content": {},
            }
        )
    )
    field = (
        SummaryField(
            field_id="summary-1",
            xml_name_property={"xml_name": "TOTAL"},
            summary_type="sum",
            related_detail_field_name="AMOUNT",
        )
        if summary
        else CommonFieldTerm(field_id=f"field-{slot}", xml_name_property={"xml_name": "AMOUNT"})
    ).model_dump(mode="json", exclude_none=True)
    content = tree["ab_content"]
    if slot == "group_by_fields":
        content[slot].append(field)
    elif tree_node_type == "ab_single_mapping_table":
        content["detail_fields"].append(field)
    elif slot == "detail_fields":
        content["detail_region"][slot].append(field)
    else:
        content["group_region"][slot].append(field)
    return GenerateNodeOperation._serialize_node(TreeNodeTerm.model_validate(tree))


def test_create_node_passes_exact_input_and_applies_add_without_mutating_or_aliasing():
    generated = {"node_id": "created-1", "tree_node_type": "simple_leaf", "meta": {"x": 1}}
    operation = RecordingOperation(
        SimpleNamespace(
            success=True,
            generated_node=generated,
            patch={"op": "add", "path": "/mapping_content/children/-", "value": generated},
        )
    )
    original = node_tree()
    before = deepcopy(original)

    result = OperationActionAdapter(generate_node_operation=operation).create_node(
        "create amount", "$.mapping_content", original
    )

    request = operation.inputs[0]
    assert request.query == "create amount"
    assert request.node_path == "$.mapping_content"
    assert request.edsl_tree == original
    assert result["created_node_id"] == "created-1"
    assert result["target_tree"]["mapping_content"]["children"][-1] == generated
    assert original == before
    generated["meta"]["x"] = 9
    assert result["target_tree"]["mapping_content"]["children"][-1]["meta"]["x"] == 1


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (SimpleNamespace(success=False, failure_reason="NODE_FAILED", generated_node=None, patch=None), "NODE_FAILED"),
        (SimpleNamespace(success=True, generated_node={"node_id": "  "}, patch={"op": "add", "path": "/x/-", "value": {}}), "node_id"),
        (SimpleNamespace(success=True, generated_node={"node_id": "ok"}, patch=None), "patch"),
    ],
)
def test_create_node_rejects_failed_or_incomplete_outputs(result, message):
    with pytest.raises(ValueError, match=message):
        OperationActionAdapter(generate_node_operation=RecordingOperation(result)).create_node("q", "$.x", {})


def test_modify_node_passes_exact_input_and_applies_multiple_patches_in_order():
    original = node_tree()
    operation = RecordingOperation(
        SimpleNamespace(
            success=True,
            patch_list=[
                {"op": "replace", "path": "/mapping_content/children/0/annotation", "value": "changed"},
                {"op": "replace", "path": "/mapping_content/children/0/data_expression/expression", "value": "new"},
            ],
        )
    )

    result = OperationActionAdapter(modify_node_operation=operation).modify_node(
        "modify leaf", "$.mapping_content.children[0]", original
    )

    request = operation.inputs[0]
    assert request.query == "modify leaf"
    assert request.node_path == "$.mapping_content.children[0]"
    assert request.edsl_tree == original
    changed = result["target_tree"]["mapping_content"]["children"][0]
    assert changed["annotation"] == "changed"
    assert changed["data_expression"]["expression"] == "new"
    assert original["mapping_content"]["children"][0]["annotation"] == "keep"


def test_modify_node_forwards_optional_site_and_project_ids():
    operation = RecordingOperation(
        SimpleNamespace(success=True, patch_list=[{"op": "replace", "path": "/value", "value": 2}])
    )

    OperationActionAdapter(modify_node_operation=operation).modify_node(
        "modify expression", "$.value", {"value": 1}, site_id="site", project_id="project"
    )

    request = operation.inputs[0]
    assert request.site_id == "site"
    assert request.project_id == "project"


@pytest.mark.parametrize(
    "result",
    [SimpleNamespace(success=False, failure_reason="MODIFY_FAILED", patch_list=[]), SimpleNamespace(success=True, patch_list=[])],
)
def test_modify_node_propagates_failure_and_requires_nonempty_patches(result):
    expected = "MODIFY_FAILED" if not result.success else "patch_list"
    with pytest.raises(ValueError, match=expected):
        OperationActionAdapter(modify_node_operation=RecordingOperation(result)).modify_node("q", "$.x", {})


@pytest.mark.parametrize(
    ("parent_type", "parent_flag", "expected_is_ab"),
    [("parent", False, False), ("ab_pivot_table", False, True), ("parent", True, True)],
)
def test_generate_expression_passes_resolved_context_and_writes_only_expression(
    parent_type, parent_flag, expected_is_ab
):
    tree = node_tree()
    parent = tree["mapping_content"]
    parent["tree_node_type"] = parent_type
    parent["is_ab"] = parent_flag
    before = deepcopy(tree)
    generator = RecordingLogicGenerator(SimpleNamespace(logic_type="expression", expression="acct.amount + 1"))

    result = OperationActionAdapter(value_logic_generator=generator).generate_expression(
        "derive amount", "$.mapping_content.children[0]", tree, site_id=None, project_id=None
    )

    request = generator.requests[0]
    assert request.site_id == ""
    assert request.project_id == ""
    assert request.node_path == "$.mapping_content.children[0]"
    assert request.node == tree["mapping_content"]["children"][0]
    assert request.parent_node == parent
    assert request.query == "derive amount"
    assert request.is_ab is expected_is_ab
    assert request.edsl_tree == tree
    expected = {"expression_type": "edsl_expression", "expression": "acct.amount + 1"}
    changed = result["target_tree"]["mapping_content"]["children"][0]
    assert changed["data_expression"] == expected
    assert {k: v for k, v in changed.items() if k != "data_expression"} == {
        k: v for k, v in before["mapping_content"]["children"][0].items() if k != "data_expression"
    }
    assert tree == before


def test_generate_expression_treats_ab_common_field_as_ab_and_preserves_ids():
    tree = ab_tree_with_field("ab_single_mapping_table", "detail_fields")
    path = build_node_index(tree)["field-detail_fields"].jsonpath
    generator = RecordingLogicGenerator(SimpleNamespace(logic_type="expression", expression="x"))

    result = OperationActionAdapter(value_logic_generator=generator).generate_expression(
        "q", path, tree, site_id="site", project_id="project"
    )

    request = generator.requests[0]
    assert (request.site_id, request.project_id, request.is_ab) == ("site", "project", True)
    assert request.parent_node["node_id"] == "ab-parent"
    field = result["target_tree"]["ab_content"]["detail_fields"][0]
    assert field["field_id"] == "field-detail_fields"
    assert field["data_source"] == {
        "data_source_type": "expression",
        "data_expression": {"expression_type": "edsl_expression", "expression": "x"},
    }
    TreeNodeTerm.model_validate(result["target_tree"])


@pytest.mark.parametrize(
    ("tree_node_type", "slot"),
    [
        ("ab_two_level_table", "group_by_fields"),
        ("ab_two_level_table", "group_related_fields"),
        ("ab_two_level_table", "detail_fields"),
        ("ab_pivot_table", "sum_fields"),
    ],
)
def test_generate_expression_writes_schema_valid_data_source_for_each_ab_common_slot(
    tree_node_type, slot
):
    tree = ab_tree_with_field(tree_node_type, slot)
    field_id = f"field-{slot}"
    path = build_node_index(tree)[field_id].jsonpath
    generator = RecordingLogicGenerator(SimpleNamespace(logic_type="expression", expression="amount + 1"))

    result = OperationActionAdapter(value_logic_generator=generator).generate_expression("q", path, tree)

    candidate = build_node_index(result["target_tree"])[field_id]
    resolved = GenerateNodeOperation().path_resolver.resolve_value(result["target_tree"], candidate.jsonpath).value
    assert resolved["data_source"]["data_source_type"] == "expression"
    assert resolved["data_source"]["data_expression"]["expression"] == "amount + 1"
    TreeNodeTerm.model_validate(result["target_tree"])


@pytest.mark.parametrize("target", ["summary", "container"])
def test_generate_expression_rejects_ab_summary_and_container_before_generator(target):
    if target == "summary":
        tree = ab_tree_with_field("ab_two_level_table", "summary_fields", summary=True)
        path = build_node_index(tree)["summary-1"].jsonpath
    else:
        tree = ab_tree_with_field("ab_pivot_table", "group_by_fields")
        path = "$"

    class ForbiddenGenerator:
        def generate(self, request):
            raise AssertionError("generator must not be called")

    with pytest.raises(ValueError, match="not support expression"):
        OperationActionAdapter(value_logic_generator=ForbiddenGenerator()).generate_expression("q", path, tree)


@pytest.mark.parametrize(
    "logic_result",
    [SimpleNamespace(logic_type="bo_field_mapping", expression="x"), SimpleNamespace(logic_type="expression", expression="  ")],
)
def test_generate_expression_rejects_non_expression_or_blank_expression(logic_result):
    with pytest.raises(ValueError, match="expression"):
        OperationActionAdapter(value_logic_generator=RecordingLogicGenerator(logic_result)).generate_expression(
            "q", "$.mapping_content.children[0]", node_tree()
        )


def test_delete_node_removes_exact_list_element_and_returns_nearest_parent_id():
    original = node_tree()
    before = deepcopy(original)

    result = OperationActionAdapter().delete_node(
        "$.mapping_content.children[1].children[0]", original
    )

    assert result["parent_node_id"] == "list-1"
    assert result["target_tree"]["mapping_content"]["children"][1]["children"] == []
    assert original == before


def test_delete_node_removes_exact_ab_field_and_returns_ab_parent_id():
    tree = ab_tree_with_field("ab_pivot_table", "sum_fields")
    path = build_node_index(tree)["field-sum_fields"].jsonpath

    result = OperationActionAdapter().delete_node(path, tree)

    assert result["parent_node_id"] == "ab-parent"
    assert result["target_tree"]["ab_content"]["group_region"]["sum_fields"] == []
    TreeNodeTerm.model_validate(result["target_tree"])


@pytest.mark.parametrize(
    ("path", "tree", "message"),
    [
        ("$", {"node_id": "root"}, "root"),
        ("$.mapping_content", node_tree(), "list"),
        ("$.mapping_content.children[0].data_expression", node_tree(), "node_id"),
        ("$.items[0]", {"items": [{"node_id": "x"}]}, "parent"),
    ],
)
def test_delete_node_rejects_root_non_list_non_node_or_missing_parent(path, tree, message):
    with pytest.raises(ValueError, match=message):
        OperationActionAdapter().delete_node(path, tree)


def test_patch_applier_decodes_escaped_pointer_segments():
    tree = {"a/b": {"~name": "old"}}
    operation = RecordingOperation(
        SimpleNamespace(
            success=True,
            patch_list=[{"op": "replace", "path": "/a~1b/~0name", "value": {"nested": []}}],
        )
    )

    result = OperationActionAdapter(modify_node_operation=operation).modify_node("q", "$.ignored", tree)

    assert result["target_tree"] == {"a/b": {"~name": {"nested": []}}}
    operation.result.patch_list[0]["value"]["nested"].append(1)
    assert result["target_tree"]["a/b"]["~name"]["nested"] == []


def test_index_path_with_quoted_keys_resolves_and_deletes_through_adapter():
    tree = {
        "a.b": {
            "node_id": "parent",
            "tree_node_type": "parent",
            "children": [{"node_id": "leaf", "tree_node_type": "simple_leaf"}],
        }
    }
    path = build_node_index(tree)["leaf"].jsonpath

    result = OperationActionAdapter().delete_node(path, tree)

    assert path == "$['a.b'].children[0]"
    assert result["parent_node_id"] == "parent"
    assert result["target_tree"]["a.b"]["children"] == []


def test_root_replace_patch_is_atomic_and_dot_segments_are_ordinary_keys():
    value = {".": {"..": "new"}}
    operation = RecordingOperation(
        SimpleNamespace(
            success=True,
            generated_node={"field_id": "field-1"},
            patch={"op": "replace", "path": "", "value": value},
        )
    )

    result = OperationActionAdapter(generate_node_operation=operation).create_node("q", "$", {"old": True})

    assert result == {"created_node_id": "field-1", "target_tree": value}


def test_index_resolver_and_adapter_create_ab_field_under_quoted_key():
    tree = {"a.b": ab_tree_with_field("ab_pivot_table", "group_by_fields")}
    tree["a.b"]["ab_content"]["group_by_fields"] = []
    operation = GenerateNodeOperation(
        common_fields_llm=lambda query: {
            "xml_name_property": {"xml_name": "AMOUNT"},
            "annotation": "amount",
            "reference_logic_area_id_list": [],
        },
        ab_field_placement_llm=lambda *args: {
            "placement": "sum_fields",
            "summary_type": None,
            "reason": "sum field",
        },
    )
    path = build_node_index(tree)["ab-parent"].jsonpath

    result = OperationActionAdapter(generate_node_operation=operation).create_node("生成金额", path, tree)

    assert path == "$['a.b']"
    assert result["created_node_id"]
    fields = result["target_tree"]["a.b"]["ab_content"]["group_region"]["sum_fields"]
    assert fields[0]["field_id"] == result["created_node_id"]
    TreeNodeTerm.model_validate(result["target_tree"]["a.b"])


def test_json_pointer_dot_and_dotdot_are_ordinary_property_keys():
    operation = RecordingOperation(
        SimpleNamespace(
            success=True,
            patch_list=[{"op": "replace", "path": "/./..", "value": "changed"}],
        )
    )

    result = OperationActionAdapter(modify_node_operation=operation).modify_node(
        "q", "$.ignored", {".": {"..": "old"}}
    )

    assert result["target_tree"] == {".": {"..": "changed"}}


@pytest.mark.parametrize(
    "patch",
    [
        {"op": "remove", "path": "/x"},
        {"op": "replace", "path": "x", "value": 1},
        {"op": "replace", "path": "/../x", "value": 1},
        {"op": "replace", "path": "/missing", "value": 1},
        {"op": "replace", "path": "/items/2", "value": 1},
        {"op": "add", "path": "/items/0", "value": 1},
        {"op": "replace", "path": "/bad~2key", "value": 1},
    ],
)
def test_patch_applier_rejects_unsupported_malformed_escape_and_out_of_range_patches(patch):
    operation = RecordingOperation(SimpleNamespace(success=True, patch_list=[patch]))
    with pytest.raises(ValueError, match="patch"):
        OperationActionAdapter(modify_node_operation=operation).modify_node(
            "q", "$.ignored", {"x": 0, "items": [0]}
        )
