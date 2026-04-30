import json
import re
from pathlib import Path

from agent.llm.config import PROJECT_ROOT


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class PromptManager:
    def __init__(self, prompt_path: str | Path | None = None):
        self.prompt_path = Path(prompt_path) if prompt_path else PROJECT_ROOT / "prompt.json"
        self._prompts: dict | None = None

    def render(self, prompt_key: str, lang: str = "zh", **variables: str) -> str:
        template = self._get_template(prompt_key, lang)
        missing = sorted(set(PLACEHOLDER_PATTERN.findall(template)) - set(variables))
        if missing:
            raise ValueError(f"Missing prompt variables for {prompt_key}: {', '.join(missing)}")

        def replace(match: re.Match[str]) -> str:
            return str(variables[match.group(1)])

        return PLACEHOLDER_PATTERN.sub(replace, template)

    def _get_template(self, prompt_key: str, lang: str) -> str:
        prompts = self._load_prompts()
        prompt_group = prompts.get(prompt_key)
        if not isinstance(prompt_group, dict):
            raise KeyError(f"Prompt key not found: {prompt_key}")
        template = prompt_group.get(lang)
        if not isinstance(template, str) or not template:
            raise KeyError(f"Prompt language not found: {prompt_key}.{lang}")
        return template

    def _load_prompts(self) -> dict:
        if self._prompts is None:
            self._prompts = json.loads(self.prompt_path.read_text(encoding="utf-8"))
        return self._prompts
