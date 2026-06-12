import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.resource_manager.loader.bo_loader import (
    _collect_naming_sql_list,
    _collect_property_list,
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
from agent.resource_manager.loader.local_context_loader import load_visible_local_context_registry
from agent.resource_manager.loader.resource_loader import ResourceLoader
from agent.resource_manager.models import NamingSqlDefTerm, ParamTerm, PropertyTerm


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


def sample_edsl_tree_payload():
    return {
        "mapping_content": {
            "tree_node_type": "parent",
            "annotation": "root node",
            "xml_name_property": {
                "xml_name": "ROOT",
            },
            "local_context": [
                {
                    "property_name": "rootLocal",
                    "annotation": "root local context",
                    "return_type": {
                        "data_type": "basic",
                        "data_type_name": "STRING",
                        "is_list": False,
                    },
                }
            ],
            "children": [
                {
                    "tree_node_type": "simple_leaf",
                    "annotation": "release",
                },
                {
                    "tree_node_type": "parent_list",
                    "annotation": "user info",
                    "xml_name_property": {
                        "xml_name": "SUB_INFO",
                    },
                    "local_context": [
                        {
                            "property_name": "local_2",
                            "annotation": "desc_2",
                            "return_type": {
                                "data_type": "basic",
                                "data_type_name": "INT32",
                                "is_list": False,
                            },
                        }
                    ],
                    "iter_local_context": [
                        {
                            "property_name": "subId",
                            "annotation": "user id",
                            "return_type": {
                                "data_type": "basic",
                                "data_type_name": "INT64",
                                "is_list": False,
                            },
                        }
                    ],
                    "children": [],
                },
            ],
        }
    }


class ResourceLoaderTest(unittest.TestCase):
    def test_load_visible_local_context_registry_for_existing_node_path(self):
        with patch("agent.resource_manager.loader.local_context_loader.parse") as parse_jsonpath:
            from jsonpath_ng import parse as real_parse

            parse_jsonpath.side_effect = real_parse
            registry = load_visible_local_context_registry(
                sample_edsl_tree_payload(),
                "$.mapping_content.children[1]",
            )

        self.assertEqual(
            [local_context.context_name for local_context in registry],
            ["$local$.rootLocal", "$local$.local_2", "$iter$.subId"],
        )
        parse_jsonpath.assert_any_call("$.mapping_content")
        parse_jsonpath.assert_any_call("$.mapping_content.children[1]")
        self.assertEqual([local_context.resource_id for local_context in registry], ["local.0000", "local.0001", "local.0002"])
        self.assertEqual(
            [local_context.source_path for local_context in registry],
            [
                "$.mapping_content.local_context[0]",
                "$.mapping_content.children[1].local_context[0]",
                "$.mapping_content.children[1].iter_local_context[0]",
            ],
        )
        self.assertEqual(registry[0].return_type.data_type, "basic")
        self.assertEqual(registry[0].tag, ["rootLocal", "ROOT", "root", "node", "local", "context", "STRING"])
        self.assertIn("local_2", registry[1].tag)
        self.assertIn("desc_2", registry[1].tag)
        self.assertIn("INT32", registry[1].tag)
        self.assertIn("subId", registry[2].tag)
        self.assertIn("id", registry[2].tag)
        self.assertIn("INT64", registry[2].tag)
        self.assertEqual(registry[2].property_type, "iter")

    def test_load_visible_local_context_registry_for_insert_position(self):
        registry = load_visible_local_context_registry(
            sample_edsl_tree_payload(),
            "$.mapping_content.children[1].children[0]",
        )

        self.assertEqual(
            [local_context.context_name for local_context in registry],
            ["$local$.rootLocal", "$local$.local_2", "$iter$.subId"],
        )

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
        self.assertEqual(registry[0].tag, ["ACCT_ID", "ACCT", "ID", "system", "account", "id", "acct", "BC_ACCT", "BC"])

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
            ["name", "custom", "order", "OrderInfo", "Order", "Info", "buyer", "BC_CUST", "BC", "CUST", "STRING"],
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
        self.assertIn("BE_ID", registry[0].tag)
        self.assertIn("billStatement", registry[0].tag)
        self.assertIn("BB_BILL_STATEMENT", registry[0].tag)
        self.assertEqual(registry[2].return_type.data_type, "basic")
        self.assertEqual(registry[2].return_type.data_type_name, "INT32")

    def test_load_bo_registry_from_json_flattens_system_and_custom_bo(self):
        registry = load_bo_registry_from_json(sample_bo_payload())
        registry_by_name = load_bo_registry_by_json(sample_bo_payload())

        self.assertEqual([bo.resource_id for bo in registry], ["bo.0000", "bo.0001"])
        self.assertEqual(registry[0].bo_name, "BB_BAK_TRANS")
        self.assertEqual(
            registry[0].tag,
            [
                "BB_BAK_TRANS",
                "BB",
                "BAK",
                "TRANS",
                "Transaction",
                "information",
                "table",
                "LOG_ID",
                "LOG",
                "ID",
                "AR",
                "log",
                "long",
                "BB_BAK_TRANS_queryDataLoadData",
                "query",
                "Data",
                "Load",
                "Query",
                "END_DATE",
                "END",
                "DATE",
                "Date",
            ],
        )
        self.assertEqual(registry[0].property_list[0].field_name, "LOG_ID")
        self.assertIsInstance(registry[0].property_list[0], PropertyTerm)
        self.assertIsInstance(registry[0].naming_sql_list[0], NamingSqlDefTerm)
        self.assertIsInstance(registry[0].naming_sql_list[0].param_list[0], ParamTerm)
        self.assertEqual(registry[0].naming_sql_list[0].sql_name, "BB_BAK_TRANS_queryDataLoadData")
        self.assertEqual(registry[1].bo_name, "CUSTOM_ACCOUNT")
        self.assertEqual(registry[1].tag, ["CUSTOM_ACCOUNT", "CUSTOM", "ACCOUNT", "Custom", "account", "table", "CUSTOM_ID", "ID", "id", "long"])
        self.assertIn("BB_BAK_TRANS", registry_by_name)

    def test_collect_naming_sql_list_normalizes_terms(self):
        bo_payload = sample_bo_payload()["sys_bo_list"][0]

        naming_sql_list = _collect_naming_sql_list(bo_payload)

        self.assertEqual(len(naming_sql_list), 1)
        self.assertIsInstance(naming_sql_list[0], NamingSqlDefTerm)
        self.assertIsInstance(naming_sql_list[0].param_list[0], ParamTerm)
        self.assertEqual(naming_sql_list[0].sql_name, "BB_BAK_TRANS_queryDataLoadData")

    def test_collect_property_list_normalizes_terms(self):
        bo_payload = sample_bo_payload()["sys_bo_list"][0]

        property_list = _collect_property_list(bo_payload)

        self.assertEqual(len(property_list), 1)
        self.assertIsInstance(property_list[0], PropertyTerm)
        self.assertEqual(property_list[0].field_name, "LOG_ID")

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
            ["CustCallMask", "Cust", "Call", "Mask", "customer", "call", "number", "DacsDataTrans", "Dacs", "Data", "Trans", "iBeId", "i", "Be", "Id", "int", "void"],
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
        self.assertEqual(loaded.domain_registry.ctx_domains, ["trans"])
        self.assertEqual(loaded.domain_registry.bo_domains, ["BB_BAK_TRANS", "CUSTOM_ACCOUNT"])
        self.assertEqual(loaded.domain_registry.func_domains, ["DacsDataTrans", "deOrg"])
        self.assertEqual(loaded.domain_registry.namingsql_domains, ["BB_BAK_TRANS"])
        self.assertEqual(loaded.edsl_tree, {"root": []})

    def test_loaded_resource_generates_visible_local_context_registry(self):
        loader = ResourceLoader(data_dir=Path("agent/resource_manager/data"))
        loaded = loader.load_resource("site1", "project1", sample_edsl_tree_payload())

        local_registry = loaded.get_visible_local_context_registry("$.mapping_content.children[1]")

        self.assertEqual(sorted(local_registry), ["$iter$.subId", "$local$.local_2", "$local$.rootLocal"])
        self.assertEqual(
            local_registry["$iter$.subId"].source_path,
            "$.mapping_content.children[1].iter_local_context[0]",
        )

    def test_load_visible_local_context_registry_reads_default_sample_tree(self):
        data_path = (
            Path(__file__).resolve().parents[1]
            / "agent"
            / "resource_manager"
            / "data"
            / "edsl_tree.json"
        )
        edsl_tree = json.loads(data_path.read_text(encoding="utf-8"))

        registry = load_visible_local_context_registry(edsl_tree, "$.mapping_content.children[1]")

        self.assertEqual(
            [local_context.context_name for local_context in registry],
            ["$local$.local_2", "$iter$.subId"],
        )
        self.assertEqual(
            [local_context.source_path for local_context in registry],
            [
                "$.mapping_content.children[1].local_context[0]",
                "$.mapping_content.children[1].iter_local_context[0]",
            ],
        )
        self.assertIn("local_2", registry[0].tag)
        self.assertIn("SUB_INFO", registry[0].tag)
        self.assertIn("subId", registry[1].tag)
        self.assertIn("SUB_INFO", registry[1].tag)

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
