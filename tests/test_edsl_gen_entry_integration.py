import os
import unittest

from agent.edsl_gen_entry import ValueLogicGenerator
from agent.llm.config import load_openai_settings
from agent.models import ValueLogicRequest


def _llm_integration_enabled() -> bool:
    return os.getenv("RUN_LLM_INTEGRATION_TEST") == "1"


@unittest.skipUnless(
    _llm_integration_enabled(),
    "Set RUN_LLM_INTEGRATION_TEST=1 to run real LLM integration tests.",
)
class EDSLGenEntryIntegrationTest(unittest.TestCase):
    def test_generate_value_logic_calls_real_llm_and_returns_expression(self):
        settings = load_openai_settings()
        self.assertTrue(settings.is_usable, "Fill .env with OPENAI_API_KEY before running this test.")

        result = ValueLogicGenerator().generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1]",
                node={
                    "node_id": "node-1",
                    "tree_node_type": "simple_leaf",
                    "xml_name_property": {"xml_name": "SUB_INFO"},
                    "description": "user information node",
                },
                query="Return one matching object by local sub id.",
            )
        )

        self.assertEqual(result.logic_type, "expression")
        self.assertTrue((result.expression or "").strip())
        self.assertNotIn("```", result.expression or "")
        self.assertNotIn("markdown", (result.expression or "").lower())


if __name__ == "__main__":
    unittest.main()
