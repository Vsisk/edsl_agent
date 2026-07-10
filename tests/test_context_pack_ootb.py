from copy import deepcopy

from agent.context_pack.models import ContextPackRequest
from agent.context_pack.project_context import ProjectContext
from agent.context_pack.providers.ootb_edsl import OotbEdslProvider
from agent.context_pack.registry import RecallProfile
from agent.context_pack.search import LocalResourceSearchTool


def ootb_tree():
    return {
        "mapping_content": {
            "node_id": "root",
            "tree_node_type": "parent",
            "annotation": "完整基线",
            "children": [
                {
                    "node_id": "full-name",
                    "tree_node_type": "simple_leaf",
                    "annotation": "客户完整姓名 title first middle last 判空拼接",
                    "xml_name_property": {"xml_name": "FULL_NAME"},
                    "data_expression": "joinNonEmpty(title, firstName, middleName, lastName)",
                },
                {
                    "node_id": "other-parent",
                    "tree_node_type": "parent_list",
                    "annotation": "客户列表",
                    "children": [{"node_id": f"child-{i}", "tree_node_type": "simple_leaf"} for i in range(20)],
                },
            ],
        }
    }


def request():
    return ContextPackRequest(
        node={"node_id": "target", "tree_node_type": "simple_leaf", "annotation": "客户姓名"},
        query="生成客户完整姓名 title 判空拼接",
        resource_names=["ootb_edsl"],
    )


def test_ootb_provider_returns_only_compatible_reference_without_mutation():
    tree = ootb_tree()
    original = deepcopy(tree)
    provider = OotbEdslProvider(LocalResourceSearchTool())

    section = provider.retrieve(request(), ProjectContext(ootb_tree=tree), RecallProfile(3, 12000))

    assert section.status.value == "ready"
    assert [item.content["name"] for item in section.items] == ["FULL_NAME"]
    assert all(item.authority.value == "reference" for item in section.items)
    assert all(item.content["tree_node_type"] == "simple_leaf" for item in section.items)
    assert tree == original


def test_ootb_provider_marks_missing_source_unavailable():
    section = OotbEdslProvider(LocalResourceSearchTool()).retrieve(
        request(), ProjectContext(), RecallProfile(3, 12000)
    )
    assert section.status.value == "unavailable"


def test_ootb_provider_does_not_widen_to_incompatible_nodes():
    req = request().model_copy(update={"node": {"node_id": "x", "tree_node_type": "ab_pivot_table"}})
    section = OotbEdslProvider(LocalResourceSearchTool()).retrieve(
        req, ProjectContext(ootb_tree=ootb_tree()), RecallProfile(3, 12000)
    )
    assert section.status.value == "empty"
    assert section.items == []
