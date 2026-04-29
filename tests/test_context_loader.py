import unittest
import json
from pathlib import Path

from agent.resource_manager.loader.context_loader import (
    load_context_registry_by_json,
    load_context_registry_from_json,
)


class ContextLoaderTest(unittest.TestCase):
    def test_loads_basic_leaf_context_registry(self):
        payload = {
            "global_context": {
                "property_name": "$ctx$",
                "sub_properties": [
                    {
                        "property_type": "system",
                        "return_type": {
                            "data_type": "bo",
                            "data_type_name": "BC_ACCT",
                            "is_list": False,
                        },
                        "property_name": "acct",
                        "children": [
                            {
                                "annotation": "account id",
                                "property_name": "ACCT_ID",
                                "return_type": {
                                    "data_type": "INT64",
                                    "data_type_name": None,
                                    "is_list": None,
                                },
                            }
                        ],
                    }
                ],
            }
        }

        registry = load_context_registry_from_json(payload)

        self.assertEqual(len(registry), 1)
        self.assertEqual(registry[0].resource_id, "ctx.0000")
        self.assertEqual(registry[0].context_name, "$ctx$.acct.ACCT_ID")
        self.assertEqual(registry[0].return_type.data_type, "INT64")
        self.assertEqual(registry[0].property_type.value, "system")
        self.assertEqual(registry[0].annotation, "account id")
        self.assertEqual(registry[0].tag, ["ACCT_ID", "system", "acct", "BC_ACCT"])

    def test_recurses_through_nested_logic_and_sub_global_context(self):
        payload = {
            "sub_global_context": {
                "sub_properties": {
                    "property_name": "$ctx$",
                    "sub_properties": [
                        {
                            "property_name": "order",
                            "property_type": "custom",
                            "annotation": "order",
                            "return_type": {
                                "data_type": "logic",
                                "data_type_name": "OrderInfo",
                                "is_list": False,
                            },
                            "children": [
                                {
                                    "property_name": "buyer",
                                    "annotation": "buyer",
                                    "return_type": {
                                        "data_type": "bo",
                                        "data_type_name": "BC_CUST",
                                        "is_list": False,
                                    },
                                    "children": [
                                        {
                                            "property_name": "name",
                                            "annotation": "name",
                                            "return_type": {
                                                "data_type": "basic",
                                                "data_type_name": "STRING",
                                                "is_list": False,
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        }

        registry = load_context_registry_from_json(payload)
        registry_by_name = load_context_registry_by_json(payload)

        self.assertEqual(len(registry), 1)
        self.assertEqual(registry[0].context_name, "$ctx$.order.buyer.name")
        self.assertEqual(registry[0].property_type.value, "custom")
        self.assertEqual(registry[0].annotation, "order.buyer.name")
        self.assertEqual(
            registry[0].tag,
            ["name", "custom", "order", "OrderInfo", "buyer", "BC_CUST", "STRING"],
        )
        self.assertIn("$ctx$.order.buyer.name", registry_by_name)
        self.assertEqual(registry_by_name["$ctx$.order.buyer.name"].resource_id, "ctx.0000")

    def test_loads_default_sample_context_data(self):
        data_path = (
            Path(__file__).resolve().parents[1]
            / "agent"
            / "resource_manager"
            / "data"
            / "context_definition.json"
        )
        payload = json.loads(data_path.read_text(encoding="utf-8"))

        registry = load_context_registry_from_json(payload)

        self.assertEqual(
            [context_registry.context_name for context_registry in registry],
            ["$ctx$.billStatement.BE_ID", "$ctx$.billStatement.CUST_ID", "$ctx$.bill_id"],
        )
        self.assertEqual([context_registry.resource_id for context_registry in registry], ["ctx.0000", "ctx.0001", "ctx.0002"])
        self.assertEqual(registry[0].tag, ["BE_ID", "system", "billStatement", "BB_BILL_STATEMENT"])
        self.assertEqual(registry[2].return_type.data_type, "basic")
        self.assertEqual(registry[2].return_type.data_type_name, "INT32")


if __name__ == "__main__":
    unittest.main()
