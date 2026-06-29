from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent.operation_orchestration.action_adapter import OperationActionAdapter


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


def test_generate_expression_treats_target_ab_type_as_ab_and_preserves_ids():
    tree = node_tree()
    tree["mapping_content"]["children"][0]["tree_node_type"] = "ab_single_mapping_table"
    generator = RecordingLogicGenerator(SimpleNamespace(logic_type="expression", expression="x"))

    OperationActionAdapter(value_logic_generator=generator).generate_expression(
        "q", "$.mapping_content.children[0]", tree, site_id="site", project_id="project"
    )

    request = generator.requests[0]
    assert (request.site_id, request.project_id, request.is_ab) == ("site", "project", True)


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
