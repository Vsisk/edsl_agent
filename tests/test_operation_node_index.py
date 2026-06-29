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
        ),
        "mapping": NodeLocateCandidate(
            node_id="mapping",
            jsonpath="$.mapping_content",
            tree_node_type="parent_list",
            xml_name="Mapping",
            parent_xml_name="Root",
            parent_node_id="root",
            child_count=1,
        ),
        "leaf": NodeLocateCandidate(
            node_id="leaf",
            jsonpath="$.mapping_content.children[0]",
            tree_node_type="field",
            xml_name="Leaf",
            parent_xml_name="Mapping",
            parent_node_id="mapping",
            child_count=0,
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
    "intent_type", ["modify_node", "generate_expression", "delete_node"]
)
def test_existing_node_intents_accept_any_indexed_node(intent_type: str) -> None:
    candidate = NodeLocateCandidate(
        node_id="leaf", jsonpath="$", tree_node_type="field"
    )

    assert is_valid_candidate(intent_type, candidate) is True


def test_unknown_intent_is_rejected() -> None:
    candidate = NodeLocateCandidate(
        node_id="leaf", jsonpath="$", tree_node_type="field"
    )

    assert is_valid_candidate("unknown", candidate) is False
