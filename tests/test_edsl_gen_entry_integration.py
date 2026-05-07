import os
import unittest

from agent.edsl_gen_entry import DSLAgent
from agent.llm.config import load_openai_settings
from agent.models import GenerateDSLRequest, NodeDef
from tests.test_environment import sample_edsl_tree_payload


def _llm_integration_enabled() -> bool:
    return os.getenv("RUN_LLM_INTEGRATION_TEST") == "1"


@unittest.skipUnless(
    _llm_integration_enabled(),
    "Set RUN_LLM_INTEGRATION_TEST=1 to run real LLM integration tests.",
)
class EDSLGenEntryIntegrationTest(unittest.TestCase):
    def test_generate_dsl_calls_real_llm_and_returns_expression(self):
        settings = load_openai_settings()
        self.assertTrue(settings.is_usable, "Fill .env with OPENAI_API_KEY before running this test.")

        response = DSLAgent().generate_dsl(
            GenerateDSLRequest(
                user_requirement="Return one matching object by local sub id.",
                node=NodeDef(
                    node_id="node-1",
                    node_path="$.mapping_content.children[1]",
                    node_name="SUB_INFO",
                    description="user information node",
                ),
                site_id="site1",
                project_id="project1",
                edsl_tree=sample_edsl_tree_payload(),
            )
        )

        self.assertTrue(response.success, response.failure_reason)
        self.assertTrue(response.dsl.strip())
        self.assertNotIn("```", response.dsl)
        self.assertNotIn("markdown", response.dsl.lower())


if __name__ == "__main__":
    unittest.main()
