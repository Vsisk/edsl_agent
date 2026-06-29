from copy import deepcopy

from agent.modify_node_operation import ModifyNodeOperation, ModifyNodeOperationInput
from models import TreeNodeTerm


def apply_replace_patch(document, patch):
    assert patch["op"] == "replace"
    segments = [
        segment.replace("~1", "/").replace("~0", "~")
        for segment in patch["path"].split("/")[1:]
    ]
    target = document
    for segment in segments[:-1]:
        target = target[int(segment)] if isinstance(target, list) else target[segment]
    final_segment = segments[-1]
    if isinstance(target, list):
        target[int(final_segment)] = patch["value"]
    else:
        target[final_segment] = patch["value"]
    return document


def test_replace_patch_updates_tree_with_valid_node():
    edsl_tree = {
        "mapping_content": {
            "tree_node_type": "parent",
            "xml_name_property": {"xml_name": "ROOT"},
            "children": [
                {
                    "tree_node_type": "simple_leaf",
                    "xml_name_property": {"xml_name": "AMOUNT"},
                    "data_expression": {},
                    "data_type_config": {"data_type": "simple_string"},
                    "support_big_cust_acct": {},
                }
            ],
        }
    }
    operation = ModifyNodeOperation(
        intent_llm=lambda query, current_node: {
            "intent_type": "modify_datatype",
            "affected_fields": ["data_type_config"],
            "reason": "test",
        },
        plan_llm=lambda query, current_node, intent: {
            "intent": intent,
            "type_field_updates": {
                "data_type_config": {"data_type": "money", "decimal_precision": "2"}
            },
        },
    )
    result = operation.execute(
        ModifyNodeOperationInput(
            query="改成金额类型，精度 2",
            node_path="$.mapping_content.children[0]",
            edsl_tree=edsl_tree,
        )
    )

    patched = apply_replace_patch(deepcopy(edsl_tree), result.patch_list[0])
    node = patched["mapping_content"]["children"][0]

    validated = TreeNodeTerm.model_validate(node)
    assert validated.data_type_config.data_type == "money"
    assert validated.data_type_config.decimal_precision == "2"
