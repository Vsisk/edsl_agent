from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    enabled: bool
    api_key: str
    base_url: str | None
    model: str
    timeout_seconds: float

    @property
    def is_usable(self) -> bool:
        return self.enabled and bool(self.api_key)


def load_openai_settings(env_path: str | Path | None = None) -> OpenAISettings:
    values = _read_env_file(Path(env_path) if env_path else PROJECT_ROOT / ".env")
    return OpenAISettings(
        enabled=_as_bool(values.get("ENABLE_LLM_RESOURCE_FILTER", "true")),
        api_key=values.get("OPENAI_API_KEY", ""),
        base_url=values.get("OPENAI_BASE_URL") or None,
        model=values.get("OPENAI_MODEL", "qwen3.5-35b-a3b"),
        timeout_seconds=_as_float(values.get("OPENAI_TIMEOUT_SECONDS"), default=30.0),
    )


def _read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _as_bool(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
