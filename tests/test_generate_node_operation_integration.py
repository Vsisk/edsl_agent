from copy import deepcopy

from agent.generate_node_operation import GenerateNodeOperation, GenerateNodeOperationInput
from models import TreeNodeTerm


def apply_add_patch(document, patch):
    assert patch["op"] == "add"
    segments = [
        segment.replace("~1", "/").replace("~0", "~")
        for segment in patch["path"].split("/")[1:]
    ]
    target = document
    for segment in segments[:-1]:
        target = target[int(segment)] if isinstance(target, list) else target[segment]
    assert segments[-1] == "-"
    target.append(patch["value"])
    return document


def test_generated_patch_appends_a_valid_tree_node():
    edsl_tree = {
        "mapping_content": {
            "tree_node_type": "parent",
            "xml_name_property": {"xml_name": "ROOT"},
            "children": [],
        }
    }
    result = GenerateNodeOperation().execute(
        GenerateNodeOperationInput(
            query="生成账户ID字段",
            node_path="$.mapping_content",
            edsl_tree=edsl_tree,
        )
    )

    patched = apply_add_patch(deepcopy(edsl_tree), result.patch)
    inserted = patched["mapping_content"]["children"][-1]

    assert TreeNodeTerm.model_validate(inserted).tree_node_type == "simple_leaf"
