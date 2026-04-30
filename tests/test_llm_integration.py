import os
import unittest

from agent.llm.config import load_openai_settings
from agent.environment.resource_filter import LLMResourceFilter
from agent.models import NodeDef
from agent.resource_manager.loader.resource_loader import ResourceLoader
from tests.test_environment import sample_edsl_tree_payload


def _llm_integration_enabled() -> bool:
    return os.getenv("RUN_LLM_INTEGRATION_TEST") == "1"


@unittest.skipUnless(
    _llm_integration_enabled(),
    "Set RUN_LLM_INTEGRATION_TEST=1 to run real LLM integration tests.",
)
class LLMIntegrationTest(unittest.TestCase):
    def test_resource_filter_calls_real_llm_and_returns_candidate_ids(self):
        settings = load_openai_settings()
        self.assertTrue(settings.is_usable, "Fill .env with OPENAI_API_KEY before running this test.")

        loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
        node_info = NodeDef(
            node_id="node-1",
            node_path="$.mapping_content.children[1]",
            node_name="SUB_INFO",
            description="customer information and masking",
        )
        candidates = {
            "global_context": list(loaded.context_registry.values()),
            "local_context": list(loaded.get_visible_local_context_registry(node_info.node_path).values()),
            "bo": list(loaded.bo_registry.values()),
            "function": list(loaded.function_registry.values()),
        }
        limits = {
            "global_context": 2,
            "local_context": 2,
            "bo": 1,
            "function": 1,
        }

        result = LLMResourceFilter().filter_resources(
            node_info=node_info,
            user_query="Mask customer call number while using transaction and customer context when relevant.",
            candidates=candidates,
            limits=limits,
        )

        self.assertIsInstance(result, dict)
        for group, limit in limits.items():
            self.assertIn(group, result)
            self.assertLessEqual(len(result[group]), limit)
            candidate_ids = {resource.resource_id for resource in candidates[group]}
            for item in result[group]:
                self.assertIn(item["resource_id"], candidate_ids)
                self.assertIsInstance(item.get("reason", ""), str)


if __name__ == "__main__":
    unittest.main()
