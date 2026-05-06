import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent.llm.config import load_openai_settings
from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.prompt_manager import PromptManager, prompt_manager


class FakeClient:
    is_usable = True

    def __init__(self, content: str = '{"ok": true}'):
        self.content = content
        self.calls = []
        self.settings = FakeSettings()

    def complete(self, **payload):
        self.calls.append(payload)
        return self.content


class FakeSettings:
    def model_for(self, llm_name: str) -> str:
        return f"{llm_name}-model"


class GenerateByLLMTest(unittest.TestCase):
    def setUp(self):
        self.original_prompts = prompt_manager._prompts
        prompt_manager._prompts = {
            "resource_filter": {"zh": "resource_filter:zh:{{user_query}}"},
            "image_extract": {"zh": "image_extract:zh:{{user_query}}"},
        }

    def tearDown(self):
        prompt_manager._prompts = self.original_prompts

    def test_base_llm_renders_template_and_returns_dict(self):
        client = FakeClient('{"selected": ["ctx.1"]}')

        result = generate_by_llm(
            prompt_template="resource_filter",
            llm_name="base",
            lang="zh",
            client=client,
            user_query="mask phone",
        )

        self.assertEqual(result, {"selected": ["ctx.1"]})
        self.assertEqual(client.calls[0]["llm_name"], "base")
        self.assertEqual(client.calls[0]["model"], "base-model")
        self.assertEqual(client.calls[0]["prompt"], "resource_filter:zh:mask phone")
        self.assertNotIn("image_url", client.calls[0])

    def test_vl_llm_converts_image_base64_to_data_url(self):
        client = FakeClient()

        result = generate_by_llm(
            prompt_template="image_extract",
            llm_name="vl",
            client=client,
            image_base64="abc123",
            image_mime_type="image/jpeg",
            user_query="read screen",
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(client.calls[0]["llm_name"], "vl")
        self.assertEqual(client.calls[0]["model"], "vl-model")
        self.assertEqual(client.calls[0]["image_url"], "data:image/jpeg;base64,abc123")

    def test_vl_llm_requires_image_base64(self):
        with self.assertRaisesRegex(ValueError, "image_base64"):
            generate_by_llm(
                prompt_template="image_extract",
                llm_name="vl",
                client=FakeClient(),
                user_query="read screen",
            )

    def test_invalid_json_raises_contextual_error(self):
        with self.assertRaisesRegex(ValueError, "resource_filter.*base"):
            generate_by_llm(
                prompt_template="resource_filter",
                client=FakeClient("not json"),
                user_query="mask phone",
            )

    def test_default_prompt_manager_is_singleton(self):
        self.assertIs(PromptManager(), prompt_manager)

    def test_settings_support_base_and_vl_models_with_legacy_fallback(self):
        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "ENABLE_LLM=true",
                        "OPENAI_API_KEY=test-key",
                        "OPENAI_MODEL=legacy-base",
                        "OPENAI_VL_MODEL=vision-model",
                    ]
                ),
                encoding="utf-8",
            )

            settings = load_openai_settings(env_path)

        self.assertTrue(settings.is_usable)
        self.assertEqual(settings.base_model, "legacy-base")
        self.assertEqual(settings.vl_model, "vision-model")
        self.assertEqual(settings.model_for("base"), "legacy-base")
        self.assertEqual(settings.model_for("vl"), "vision-model")


if __name__ == "__main__":
    unittest.main()
