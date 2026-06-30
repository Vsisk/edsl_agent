from __future__ import annotations

import pytest

from agent.operation_orchestration.node_index import (
    CREATE_PARENT_TYPES,
    NodeLocateCandidate,
    build_node_index,
    is_valid_candidate,
)


def test_build_node_index_records_paths_metadata_parents_and_child_count() -> None:
    target_tree = {
        "node_id": "root",
        "tree_node_type": "parent",
        "xml_name_property": {"xml_name": "Root"},
        "annotation": "root annotation",
        "mapping_content": {
            "node_id": "mapping",
            "tree_node_type": "parent_list",
            "xml_name_property": {"xml_name": "Mapping"},
            "children": [
                {
                    "node_id": "leaf",
                    "tree_node_type": "field",
                    "xml_name_property": {"xml_name": "Leaf"},
                }
            ],
        },
    }

    index = build_node_index(target_tree)

    assert index == {
        "root": NodeLocateCandidate(
            node_id="root",
            jsonpath="$",
            tree_node_type="parent",
            xml_name="Root",
            annotation="root annotation",
            child_count=0,
            identity_field="node_id",
        ),
        "mapping": NodeLocateCandidate(
            node_id="mapping",
            jsonpath="$.mapping_content",
            tree_node_type="parent_list",
            xml_name="Mapping",
            parent_xml_name="Root",
            parent_node_id="root",
            child_count=1,
            identity_field="node_id",
        ),
        "leaf": NodeLocateCandidate(
            node_id="leaf",
            jsonpath="$.mapping_content.children[0]",
            tree_node_type="field",
            xml_name="Leaf",
            parent_xml_name="Mapping",
            parent_node_id="mapping",
            child_count=0,
            identity_field="node_id",
        ),
    }


def test_build_node_index_traverses_dicts_and_lists_in_dfs_order() -> None:
    target_tree = {
        "first": [
            {"node_id": "a", "tree_node_type": "field"},
            {
                "node_id": "b",
                "tree_node_type": "parent",
                "nested": {"node_id": "c", "tree_node_type": "field"},
            },
        ],
        "second": {"node_id": "d", "tree_node_type": "field"},
    }

    assert list(build_node_index(target_tree)) == ["a", "b", "c", "d"]


def test_missing_id_is_not_indexed_but_descendants_keep_nearest_indexed_parent() -> None:
    target_tree = {
        "node_id": "root",
        "tree_node_type": "parent",
        "xml_name_property": {"xml_name": "Root"},
        "wrapper": {
            "tree_node_type": "parent_list",
            "xml_name_property": {"xml_name": "Ignored wrapper"},
            "child": {"node_id": "leaf", "tree_node_type": "field"},
        },
    }

    index = build_node_index(target_tree)

    assert list(index) == ["root", "leaf"]
    assert index["leaf"].jsonpath == "$.wrapper.child"
    assert index["leaf"].parent_node_id == "root"
    assert index["leaf"].parent_xml_name == "Root"


def test_nodes_require_both_non_empty_id_and_type_but_traversal_continues() -> None:
    target_tree = {
        "empty_id": {
            "node_id": "",
            "tree_node_type": "parent",
            "child": {"node_id": "valid", "tree_node_type": "field"},
        },
        "empty_type": {"node_id": "ignored", "tree_node_type": ""},
    }

    assert list(build_node_index(target_tree)) == ["valid"]


def test_jsonpath_bracket_quotes_non_identifier_keys_and_escapes_them() -> None:
    target_tree = {
        "not.an identifier": {
            "quote'and\\slash": {"node_id": "leaf", "tree_node_type": "field"}
        }
    }

    candidate = build_node_index(target_tree)["leaf"]

    assert candidate.jsonpath == "$['not.an identifier']['quote\\'and\\\\slash']"


def test_duplicate_indexed_node_id_is_rejected() -> None:
    target_tree = {
        "left": {"node_id": "same", "tree_node_type": "field"},
        "right": {"node_id": "same", "tree_node_type": "field"},
    }

    with pytest.raises(ValueError, match="duplicate node_id"):
        build_node_index(target_tree)


@pytest.mark.parametrize(
    ("tree_node_type", "slot", "field_path", "expected_type"),
    [
        ("ab_single_mapping_table", "detail_fields", "ab_content.detail_fields", "ab_field"),
        ("ab_two_level_table", "group_by_fields", "ab_content.group_by_fields", "ab_field"),
        ("ab_two_level_table", "group_related_fields", "ab_content.group_region.group_related_fields", "ab_field"),
        ("ab_two_level_table", "summary_fields", "ab_content.group_region.summary_fields", "ab_summary_field"),
        ("ab_two_level_table", "detail_fields", "ab_content.detail_region.detail_fields", "ab_field"),
        ("ab_pivot_table", "group_by_fields", "ab_content.group_by_fields", "ab_field"),
        ("ab_pivot_table", "group_related_fields", "ab_content.group_region.group_related_fields", "ab_field"),
        ("ab_pivot_table", "sum_fields", "ab_content.group_region.sum_fields", "ab_field"),
    ],
)
def test_indexes_ab_fields_in_every_known_slot(
    tree_node_type: str, slot: str, field_path: str, expected_type: str
) -> None:
    field = {
        "field_id": f"field-{slot}",
        "xml_name_property": {"xml_name": "Amount"},
        "annotation": "field annotation",
    }
    content: dict = {}
    current = content
    parts = field_path.split(".")[1:]
    for part in parts[:-1]:
        current[part] = {}
        current = current[part]
    current[parts[-1]] = [field]
    tree = {
        "node_id": "ab-parent",
        "tree_node_type": tree_node_type,
        "xml_name_property": {"xml_name": "AB Parent"},
        "ab_content": content,
    }

    candidate = build_node_index(tree)[field["field_id"]]

    assert candidate.identity_field == "field_id"
    assert candidate.field_slot == slot
    assert candidate.tree_node_type == expected_type
    assert candidate.parent_node_id == "ab-parent"
    assert candidate.parent_xml_name == "AB Parent"
    assert candidate.jsonpath == f"$.{field_path}[0]"


def test_does_not_index_field_id_outside_known_ab_slots() -> None:
    tree = {
        "node_id": "ab",
        "tree_node_type": "ab_pivot_table",
        "ab_content": {"unknown_fields": [{"field_id": "ignored"}]},
    }

    assert list(build_node_index(tree)) == ["ab"]


@pytest.mark.parametrize(
    "tree",
    [
        {
            "node_id": "same",
            "tree_node_type": "ab_single_mapping_table",
            "ab_content": {"detail_fields": [{"field_id": "same"}]},
        },
        {
            "node_id": "ab",
            "tree_node_type": "ab_single_mapping_table",
            "ab_content": {"detail_fields": [{"field_id": "same"}, {"field_id": "same"}]},
        },
    ],
)
def test_rejects_identity_collisions_across_node_and_ab_field_ids(tree: dict) -> None:
    with pytest.raises(ValueError, match="duplicate node_id"):
        build_node_index(tree)


@pytest.mark.parametrize(
    "tree_node_type",
    [
        "parent",
        "parent_list",
        "ab_single_mapping_table",
        "ab_two_level_table",
        "ab_pivot_table",
    ],
)
def test_create_accepts_each_container_type(tree_node_type: str) -> None:
    candidate = NodeLocateCandidate(
        node_id="candidate",
        jsonpath="$",
        tree_node_type=tree_node_type,
    )

    assert is_valid_candidate("create_node", candidate) is True


def test_create_parent_types_are_exactly_the_supported_containers() -> None:
    assert CREATE_PARENT_TYPES == {
        "parent",
        "parent_list",
        "ab_single_mapping_table",
        "ab_two_level_table",
        "ab_pivot_table",
    }


def test_create_rejects_leaf_nodes() -> None:
    candidate = NodeLocateCandidate(
        node_id="leaf", jsonpath="$", tree_node_type="field"
    )

    assert is_valid_candidate("create_node", candidate) is False


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (NodeLocateCandidate(node_id="leaf", jsonpath="$", tree_node_type="simple_leaf", identity_field="node_id"), True),
        (NodeLocateCandidate(node_id="field", jsonpath="$", tree_node_type="ab_field", identity_field="field_id"), True),
        (NodeLocateCandidate(node_id="summary", jsonpath="$", tree_node_type="ab_summary_field", identity_field="field_id"), False),
        (NodeLocateCandidate(node_id="parent", jsonpath="$", tree_node_type="parent", identity_field="node_id"), False),
        (NodeLocateCandidate(node_id="ab", jsonpath="$", tree_node_type="ab_pivot_table", identity_field="node_id"), False),
    ],
)
def test_generate_expression_accepts_only_expression_capable_candidates(candidate, expected) -> None:
    assert is_valid_candidate("generate_expression", candidate) is expected


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (NodeLocateCandidate(node_id="leaf", jsonpath="$", tree_node_type="simple_leaf", identity_field="node_id"), True),
        (NodeLocateCandidate(node_id="field", jsonpath="$", tree_node_type="ab_field", identity_field="field_id"), False),
        (NodeLocateCandidate(node_id="legacy", jsonpath="$", tree_node_type="simple_leaf"), False),
    ],
)
def test_modify_accepts_only_canonical_standard_node_id_candidates(candidate, expected) -> None:
    assert is_valid_candidate("modify_node", candidate) is expected


@pytest.mark.parametrize(
    "candidate",
    [
        NodeLocateCandidate(node_id="leaf", jsonpath="$", tree_node_type="simple_leaf", identity_field="node_id"),
        NodeLocateCandidate(node_id="field", jsonpath="$", tree_node_type="ab_field", identity_field="field_id"),
        NodeLocateCandidate(node_id="summary", jsonpath="$", tree_node_type="ab_summary_field", identity_field="field_id"),
    ],
)
def test_delete_accepts_every_indexed_candidate(candidate) -> None:
    assert is_valid_candidate("delete_node", candidate) is True


def test_unknown_intent_is_rejected() -> None:
    candidate = NodeLocateCandidate(
        node_id="leaf", jsonpath="$", tree_node_type="field"
    )

    assert is_valid_candidate("unknown", candidate) is False
