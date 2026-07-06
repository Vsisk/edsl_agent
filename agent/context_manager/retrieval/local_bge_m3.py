from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any, Callable

from agent.context_manager.errors import AI_CONFIGURATION_REQUIRED, EMBEDDING_FAILED, ContextBuildError
from agent.llm.config import OpenAISettings

ModelLoader = Callable[[Path, str, bool], Any]
CudaAvailable = Callable[[], bool]


class LocalBGEM3Provider:
    """Lazy, process-wide BGE-M3 dense embedding provider."""

    _models: dict[tuple[str, str], Any] = {}
    _model_lock = threading.RLock()

    def __init__(self, settings: OpenAISettings, model_loader: ModelLoader | None = None,
                 cuda_available: CudaAvailable | None = None) -> None:
        self.settings = settings
        self._model_loader = model_loader or _load_sentence_transformer
        self._cuda_available = cuda_available or _torch_cuda_available

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model_path, device = self._validated_configuration()
        try:
            model = self._get_model(model_path, device)
            model.max_seq_length = self.settings.local_embedding_max_length
            output = model.encode(
                texts,
                batch_size=self.settings.local_embedding_batch_size,
                normalize_embeddings=self.settings.local_embedding_normalize,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            return _validated_vectors(output, len(texts))
        except ContextBuildError:
            raise
        except Exception as exc:
            raise ContextBuildError(EMBEDDING_FAILED) from exc

    def _validated_configuration(self) -> tuple[Path, str]:
        model_path = Path(self.settings.local_embedding_model_path).expanduser()
        if not model_path.is_dir():
            raise ContextBuildError(AI_CONFIGURATION_REQUIRED)
        requested_device = self.settings.local_embedding_device.strip().lower()
        if requested_device not in {"cuda", "cpu"}:
            raise ContextBuildError(AI_CONFIGURATION_REQUIRED)
        device = "cuda" if requested_device == "cuda" and self._cuda_available() else "cpu"
        return model_path.resolve(), device

    @property
    def effective_device(self) -> str:
        """Return the device after applying CUDA availability fallback."""
        return self._validated_configuration()[1]

    def _get_model(self, model_path: Path, device: str) -> Any:
        key = (str(model_path).casefold(), device)
        with self._model_lock:
            model = self._models.get(key)
            if model is None:
                try:
                    model = self._model_loader(model_path, device, device == "cuda")
                except ContextBuildError:
                    raise
                except Exception as exc:
                    raise ContextBuildError(EMBEDDING_FAILED) from exc
                self._models[key] = model
            return model

    @classmethod
    def clear_model_cache_for_tests(cls) -> None:
        with cls._model_lock:
            cls._models.clear()


def _load_sentence_transformer(model_path: Path, device: str, use_fp16: bool) -> Any:
    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        raise ContextBuildError(EMBEDDING_FAILED) from exc
    if device == "cuda" and not torch.cuda.is_available():
        raise ContextBuildError(AI_CONFIGURATION_REQUIRED)
    model = SentenceTransformer(str(model_path), device=device)
    model.half() if use_fp16 else model.float()
    return model


def _torch_cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _validated_vectors(output: Any, expected_count: int) -> list[list[float]]:
    raw = output.tolist() if hasattr(output, "tolist") else output
    if not isinstance(raw, (list, tuple)) or len(raw) != expected_count:
        raise ContextBuildError(EMBEDDING_FAILED)
    vectors: list[list[float]] = []
    dimension: int | None = None
    for row in raw:
        if not isinstance(row, (list, tuple)) or not row:
            raise ContextBuildError(EMBEDDING_FAILED)
        vector: list[float] = []
        for value in row:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContextBuildError(EMBEDDING_FAILED)
            number = float(value)
            if not math.isfinite(number):
                raise ContextBuildError(EMBEDDING_FAILED)
            vector.append(number)
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise ContextBuildError(EMBEDDING_FAILED)
        vectors.append(vector)
    return vectors
