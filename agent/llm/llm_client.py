from typing import Any

from openai import BadRequestError, OpenAI

from agent.llm.config import OpenAISettings, load_openai_settings
from agent.llm.llm_post_processor import parse_json_response


class LLMClient:
    def __init__(self, settings: OpenAISettings | None = None):
        self.settings = settings or load_openai_settings()
        self._client: OpenAI | None = None

    @property
    def is_usable(self) -> bool:
        return self.settings.is_usable

    def complete_json(self, prompt: str) -> dict[str, Any]:
        if not self.is_usable:
            raise RuntimeError("OpenAI settings are not usable")

        messages = [
            {
                "role": "system",
                "content": "You are a strict JSON API. Return only valid JSON.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        try:
            response = self._get_client().chat.completions.create(
                model=self.settings.model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except (TypeError, BadRequestError):
            response = self._get_client().chat.completions.create(
                model=self.settings.model,
                messages=messages,
                temperature=0,
            )
        content = response.choices[0].message.content or "{}"
        return parse_json_response(content)

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_seconds,
            )
        return self._client
