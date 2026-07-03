from typing import Any, Protocol

from openai import OpenAI

from agent.context_manager.errors import (
    AI_CONFIGURATION_REQUIRED,
    EMBEDDING_FAILED,
    ContextBuildError,
)
from agent.llm.config import OpenAISettings, load_openai_settings


class EmbeddingClientProtocol(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingClient:
    def __init__(self, settings: OpenAISettings | None = None, provider: Any = None) -> None:
        self.settings = settings or load_openai_settings()
        self._client: OpenAI | None = None
        self._provider = provider

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        provider = self.settings.embedding_provider.strip().lower()
        if self._provider is not None:
            return self._provider.embed_texts(texts)
        if provider == "local_bge_m3":
            from agent.context_manager.retrieval.local_bge_m3 import LocalBGEM3Provider
            self._provider = LocalBGEM3Provider(self.settings)
            return self._provider.embed_texts(texts)
        if provider != "openai":
            raise ContextBuildError(AI_CONFIGURATION_REQUIRED)
        if not self.settings.is_usable or not self.settings.embedding_model:
            raise ContextBuildError(AI_CONFIGURATION_REQUIRED)
        try:
            response = self._get_client().embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
            )
            data = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in data] != list(range(len(texts))):
                raise ValueError("embedding response indexes are invalid")
            vectors = [list(item.embedding) for item in data]
            if len(vectors) != len(texts):
                raise ValueError("embedding response count mismatch")
            return vectors
        except ContextBuildError:
            raise
        except Exception as exc:
            raise ContextBuildError(EMBEDDING_FAILED) from exc

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_seconds,
            )
        return self._client
