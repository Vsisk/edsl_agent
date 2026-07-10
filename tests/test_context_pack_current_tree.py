from copy import deepcopy

from agent.context_pack.models import ContextPackRequest
from agent.context_pack.project_context import ProjectContext
from agent.context_pack.providers.current_tree import CurrentTreeProvider
from agent.context_pack.registry import RecallProfile
from agent.context_pack.search import LocalResourceSearchTool


def current_tree():
    return {
        "mapping_content": {
            "node_id": "root",
            "tree_node_type": "parent",
            "children": [{
                "node_id": "customers",
                "tree_node_type": "parent_list",
                "xml_name_property": {"xml_name": "CUSTOMERS"},
                "local_context": [
                    {"property_name": "title", "annotation": "客户称谓", "return_type": {"data_type": "basic", "data_type_name": "String", "is_list": False}}
                ],
                "iter_local_context": [
                    {"property_name": "customer", "annotation": "当前客户", "return_type": {"data_type": "bo", "data_type_name": "Customer", "is_list": False}}
                ],
                "children": [{
                    "node_id": "customer-name",
                    "tree_node_type": "simple_leaf",
                    "annotation": "客户姓名",
                    "xml_name_property": {"xml_name": "NAME"},
                    "data_type_config": {"data_type": "String"},
                }],
            }],
        }
    }


def request(node_id="customer-name"):
    return ContextPackRequest(
        node={"node_id": node_id, "annotation": "客户姓名", "tree_node_type": "simple_leaf"},
        query="客户姓名 title 当前客户",
        resource_names=["current_tree"],
    )


def test_provider_returns_existing_field_and_visible_local_iter_without_mutation():
    tree = current_tree()
    original = deepcopy(tree)
    provider = CurrentTreeProvider(LocalResourceSearchTool())

    section = provider.retrieve(request(), ProjectContext(current_tree=tree), RecallProfile(10, 12000))

    assert section.status.value == "ready"
    assert {item.item_type for item in section.items} >= {"field", "local", "iter"}
    assert {item.content.get("name") for item in section.items} >= {"NAME", "title", "customer"}
    assert all(item.authority.value == "authoritative" for item in section.items)
    assert tree == original


def test_provider_returns_error_when_current_node_is_not_in_tree():
    section = CurrentTreeProvider(LocalResourceSearchTool()).retrieve(
        request("missing"), ProjectContext(current_tree=current_tree()), RecallProfile(10, 12000)
    )

    assert section.status.value == "error"
    assert section.warnings[0].code == "CURRENT_NODE_NOT_FOUND"


def test_provider_marks_missing_current_tree_unavailable():
    section = CurrentTreeProvider(LocalResourceSearchTool()).retrieve(
        request(), ProjectContext(), RecallProfile(10, 12000)
    )
    assert section.status.value == "unavailable"
