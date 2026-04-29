import json
import tempfile
import unittest
from pathlib import Path

from agent.resource_manager.loader.bo_loader import (
    load_bo_registry_by_json,
    load_bo_registry_from_json,
)
from agent.resource_manager.loader.context_loader import (
    load_context_registry_by_json,
    load_context_registry_from_json,
)
from agent.resource_manager.loader.function_loader import (
    load_function_registry_by_json,
    load_function_registry_from_json,
)
from agent.resource_manager.loader.resource_loader import ResourceLoader


def sample_bo_payload():
    return {
        "custom_bo_list": [
            {
                "bo_name": "CUSTOM_ACCOUNT",
                "bo_desc": "Custom account table.",
                "property_list": [
                    {
                        "field_name": "CUSTOM_ID",
                        "description": "Custom id.",
                        "is_list": False,
                        "data_type": "key",
                        "data_type_name": "long",
                    }
                ],
            }
        ],
        "sys_bo_list": [
            {
                "bo_name": "BB_BAK_TRANS",
                "bo_desc": "Transaction information table.",
                "or_mapping_list": [
                    {
                        "naming_sql_list": [
                            {
                                "naming_sql_id": "2025112610460822566018",
                                "sql_name": "BB_BAK_TRANS_queryDataLoadData",
                                "sql_description": "Query the BB_BAK_TRANS table.",
                                "param_list": [
                                    {
                                        "param_name": "END_DATE",
                                        "is_list": False,
                                        "data_type": "basic",
                                        "data_type_name": "Date",
                                    }
                                ],
                            }
                        ]
                    }
                ],
                "property_list": [
                    {
                        "field_name": "LOG_ID",
                        "description": "AR log ID.",
                        "is_list": False,
                        "data_type": "key",
                        "data_type_name": "long",
                    }
                ],
            }
        ],
    }


def sample_function_payload():
    return {
        "func": [
            {
                "class_name": "deOrg",
                "func_list": [
                    {
                        "func_desc": "getClassifyByRAcctId",
                        "func_name": "getClassifyByRAcctId",
                        "param_list": [
                            {
                                "param_name": "rAcctId",
                                "is_list": False,
                                "data_type": "basic",
                                "data_type_name": "long",
                            }
                        ],
                    }
                ],
            }
        ],
        "native_func": [
            {
                "class_name": "DacsDataTrans",
                "func_list": [
                    {
                        "func_desc": "mask customer call number",
                        "func_name": "CustCallMask",
                        "param_list": [
                            {
                                "param_name": "iBeId",
                                "is_list": False,
                                "data_type": "basic",
                                "data_type_name": "int",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def sample_context_payload():
    return {
        "global_context": {
            "property_name": "$ctx$",
            "sub_properties": [
                {
                    "annotation": "Transaction context",
                    "property_name": "trans",
                    "property_type": "system",
                    "return_type": {
                        "data_type": "bo",
                        "data_type_name": "BB_BAK_TRANS",
                        "is_list": False,
                    },
                    "children": [
                        {
                            "annotation": "AR log ID.",
                            "property_name": "LOG_ID",
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


class ResourceLoaderTest(unittest.TestCase):
    def test_load_context_registry_from_json_loads_basic_leaf(self):
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

    def test_load_context_registry_from_json_recurses_through_nested_context(self):
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

    def test_load_context_registry_from_json_reads_default_sample_data(self):
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
        self.assertEqual(
            [context_registry.resource_id for context_registry in registry],
            ["ctx.0000", "ctx.0001", "ctx.0002"],
        )
        self.assertEqual(registry[0].tag, ["BE_ID", "system", "billStatement", "BB_BILL_STATEMENT"])
        self.assertEqual(registry[2].return_type.data_type, "basic")
        self.assertEqual(registry[2].return_type.data_type_name, "INT32")

    def test_load_bo_registry_from_json_flattens_system_and_custom_bo(self):
        registry = load_bo_registry_from_json(sample_bo_payload())
        registry_by_name = load_bo_registry_by_json(sample_bo_payload())

        self.assertEqual([bo.resource_id for bo in registry], ["bo.0000", "bo.0001"])
        self.assertEqual(registry[0].bo_name, "BB_BAK_TRANS")
        self.assertEqual(
            registry[0].tag,
            ["BB_BAK_TRANS", "BB", "BAK", "TRANS", "Transaction", "information", "table"],
        )
        self.assertEqual(registry[0].property_list[0].field_name, "LOG_ID")
        self.assertEqual(registry[0].naming_sql_list[0].sql_name, "BB_BAK_TRANS_queryDataLoadData")
        self.assertEqual(registry[1].bo_name, "CUSTOM_ACCOUNT")
        self.assertEqual(registry[1].tag, ["CUSTOM_ACCOUNT", "CUSTOM", "ACCOUNT", "Custom", "account", "table"])
        self.assertIn("BB_BAK_TRANS", registry_by_name)

    def test_load_function_registry_from_json_flattens_script_and_native_functions(self):
        registry = load_function_registry_from_json(sample_function_payload())
        registry_by_name = load_function_registry_by_json(sample_function_payload())

        self.assertEqual([func.resource_id for func in registry], ["func.0000", "func.0001"])
        self.assertEqual(registry[0].func_name, "getClassifyByRAcctId")
        self.assertEqual(registry[0].func_class, "deOrg")
        self.assertEqual(registry[0].param_list[0].param_name, "rAcctId")
        self.assertEqual(registry[0].return_type.data_type.value, "basic")
        self.assertEqual(registry[0].return_type.data_type_name, "void")
        self.assertEqual(registry[1].func_name, "CustCallMask")
        self.assertEqual(
            registry[1].tag,
            ["CustCallMask", "Cust", "Call", "Mask", "customer", "call", "number"],
        )
        self.assertIn("CustCallMask", registry_by_name)

    def test_resource_loader_reads_files_and_generates_registries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "context_definition.json").write_text(
                json.dumps(sample_context_payload()),
                encoding="utf-8",
            )
            (data_dir / "bo_def_ootb.json").write_text(
                json.dumps(sample_bo_payload()),
                encoding="utf-8",
            )
            (data_dir / "edsl_func.json").write_text(
                json.dumps(sample_function_payload()),
                encoding="utf-8",
            )

            loader = ResourceLoader(data_dir=data_dir)
            loaded = loader.load_resource("site1", "project1", {"root": []})

        self.assertEqual(sorted(loaded.context_registry), ["$ctx$.trans.LOG_ID"])
        self.assertEqual(sorted(loaded.bo_registry), ["BB_BAK_TRANS", "CUSTOM_ACCOUNT"])
        self.assertEqual(sorted(loaded.function_registry), ["CustCallMask", "getClassifyByRAcctId"])
        self.assertEqual(loaded.edsl_tree, {"root": []})

    def test_resource_loader_reads_default_sample_data(self):
        loaded = ResourceLoader().load_resource("sample_site", "sample_project", {"sample": True})

        self.assertEqual(
            sorted(loaded.context_registry),
            ["$ctx$.billStatement.BE_ID", "$ctx$.billStatement.CUST_ID", "$ctx$.bill_id"],
        )
        self.assertEqual(sorted(loaded.bo_registry), ["BB_BAK_TRANS"])
        self.assertEqual(sorted(loaded.function_registry), ["CustCallMask", "getClassifyByRAcctId"])
        self.assertIn("Transaction", loaded.bo_registry["BB_BAK_TRANS"].tag)
        self.assertIn("Mask", loaded.function_registry["CustCallMask"].tag)
        self.assertEqual(loaded.bo_registry["BB_BAK_TRANS"].property_list[0].field_name, "LOG_ID")
        self.assertEqual(
            loaded.bo_registry["BB_BAK_TRANS"].naming_sql_list[0].param_list[0].param_name,
            "END_DATE",
        )
        self.assertEqual(
            loaded.function_registry["getClassifyByRAcctId"].param_list[0].param_name,
            "rAcctId",
        )
        self.assertEqual(loaded.edsl_tree, {"sample": True})


if __name__ == "__main__":
    unittest.main()
