from typing import Any

from openai import BadRequestError, OpenAI

from agent.llm.config import OpenAISettings, load_openai_settings

class LLMClient:
    def __init__(self, settings: OpenAISettings | None = None):
        self.settings = settings or load_openai_settings()
        self._client: OpenAI | None = None

    @property
    def is_usable(self) -> bool:
        return self.settings.is_usable

    def complete(
        self,
        *,
        prompt: str,
        model: str,
        llm_name: str = "base",
        image_url: str | None = None,
    ) -> str:
        if not self.is_usable:
            raise RuntimeError("OpenAI settings are not usable")

        user_content: str | list[dict[str, Any]]
        if llm_name == "vl":
            if not image_url:
                raise ValueError("image_url is required for vl payload")
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        elif llm_name == "base":
            user_content = prompt
        else:
            raise ValueError(f"Unsupported llm_name: {llm_name}")

        messages = [
            {
                "role": "system",
                "content": "You are a strict JSON API. Return only valid JSON.",
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]
        try:
            response = self._get_client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except (TypeError, BadRequestError):
            response = self._get_client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
            )
        content = response.choices[0].message.content or "{}"
        return content

    def complete_json(self, prompt: str) -> dict[str, Any]:
        from agent.llm.llm_post_processor import parse_json_response

        content = self.complete(
            prompt=prompt,
            model=self.settings.model_for("base"),
            llm_name="base",
        )
        return parse_json_response(content)

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_seconds,
            )
        return self._client
