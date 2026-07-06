from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    enabled: bool
    api_key: str
    base_url: str | None
    base_model: str
    vl_model: str
    timeout_seconds: float
    embedding_model: str = "bge-m3"
    embedding_provider: str = "local_bge_m3"
    local_embedding_model_path: str = r"D:\models\bge-m3"
    local_embedding_device: str = "cuda"
    local_embedding_batch_size: int = 8
    local_embedding_max_length: int = 4096
    local_embedding_normalize: bool = True

    @property
    def is_usable(self) -> bool:
        return self.enabled and bool(self.api_key)

    @property
    def model(self) -> str:
        return self.base_model

    def model_for(self, llm_name: str) -> str:
        if llm_name == "base":
            return self.base_model
        if llm_name == "vl":
            return self.vl_model
        raise ValueError(f"Unsupported llm_name: {llm_name}")


def load_openai_settings(env_path: str | Path | None = None) -> OpenAISettings:
    values = _read_env_file(Path(env_path) if env_path else PROJECT_ROOT / ".env")
    base_model = values.get("OPENAI_BASE_MODEL") or values.get("OPENAI_MODEL", "qwen3.5-35b-a3b")
    return OpenAISettings(
        enabled=_as_bool(values.get("ENABLE_LLM", values.get("ENABLE_LLM_RESOURCE_FILTER", "true"))),
        api_key=values.get("OPENAI_API_KEY", ""),
        base_url=values.get("OPENAI_BASE_URL") or None,
        base_model=base_model,
        vl_model=values.get("OPENAI_VL_MODEL", base_model),
        timeout_seconds=_as_float(values.get("OPENAI_TIMEOUT_SECONDS"), default=30.0),
        embedding_model=values.get("OPENAI_EMBEDDING_MODEL", "bge-m3"),
        embedding_provider=values.get("EMBEDDING_PROVIDER", "local_bge_m3"),
        local_embedding_model_path=values.get("LOCAL_EMBEDDING_MODEL_PATH", r"D:\models\bge-m3"),
        local_embedding_device=values.get("LOCAL_EMBEDDING_DEVICE", "cuda"),
        local_embedding_batch_size=_as_positive_int(values.get("LOCAL_EMBEDDING_BATCH_SIZE"), 8),
        local_embedding_max_length=_as_positive_int(values.get("LOCAL_EMBEDDING_MAX_LENGTH"), 4096),
        local_embedding_normalize=_as_bool(values.get("LOCAL_EMBEDDING_NORMALIZE", "true")),
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


def _as_positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
