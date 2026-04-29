import json
import tempfile
import unittest
from pathlib import Path

from agent.resource_manager.loader.bo_loader import (
    load_bo_registry_by_json,
    load_bo_registry_from_json,
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


class BoFunctionResourceLoaderTest(unittest.TestCase):
    def test_load_bo_registry_from_json_flattens_system_and_custom_bo(self):
        registry = load_bo_registry_from_json(sample_bo_payload())
        registry_by_name = load_bo_registry_by_json(sample_bo_payload())

        self.assertEqual([bo.resource_id for bo in registry], ["bo.0000", "bo.0001"])
        self.assertEqual(registry[0].bo_name, "BB_BAK_TRANS")
        self.assertEqual(registry[0].property_list[0].field_name, "LOG_ID")
        self.assertEqual(registry[0].naming_sql_list[0].sql_name, "BB_BAK_TRANS_queryDataLoadData")
        self.assertEqual(registry[1].bo_name, "CUSTOM_ACCOUNT")
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
