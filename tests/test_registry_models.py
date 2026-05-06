from pathlib import Path
import unittest

from agent.resource_manager import models
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    ContextRegistry,
    DataTypeEnum,
    FunctionRegistry,
    ReturnType,
)


class RegistryModelsTest(unittest.TestCase):
    def test_models_are_exported_from_single_registry_module(self):
        self.assertIs(models.BoRegistry, BoRegistry)
        self.assertIs(models.ContextRegistry, ContextRegistry)
        self.assertIs(models.FunctionRegistry, FunctionRegistry)
        self.assertEqual(DataTypeEnum.basic.value, "basic")

        context_registry = ContextRegistry(
            resource_id="ctx.0000",
            context_name="$ctx$.acct.ACCT_ID",
            return_type=ReturnType(data_type="INT64", data_type_name=None, is_list=None),
            property_type="system",
            annotation="account id",
        )
        self.assertEqual(context_registry.return_type.data_type, "INT64")

    def test_old_split_model_files_are_removed(self):
        models_dir = Path(__file__).resolve().parents[1] / "agent" / "resource_manager" / "models"

        self.assertFalse((models_dir / "bo_models.py").exists())
        self.assertFalse((models_dir / "context_models.py").exists())
        self.assertFalse((models_dir / "function_models.py").exists())


if __name__ == "__main__":
    unittest.main()
