import math
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.context_manager.errors import AI_CONFIGURATION_REQUIRED, EMBEDDING_FAILED, ContextBuildError
from agent.context_manager.retrieval.local_bge_m3 import LocalBGEM3Provider
from agent.llm.config import OpenAISettings


class FakeArray:
    def __init__(self, rows): self.rows = rows
    def tolist(self): return self.rows


class FakeModel:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [[1.0, 0.0], [0.0, 1.0]]
        self.calls = []
        self.max_seq_length = None
    def encode(self, texts, **kwargs):
        self.calls.append((list(texts), kwargs))
        return FakeArray(self.rows[:len(texts)])


def settings(path, **updates):
    values = dict(
        enabled=True, api_key="", base_url=None, base_model="base", vl_model="vl",
        timeout_seconds=30, embedding_provider="local_bge_m3", embedding_model="bge-m3",
        local_embedding_model_path=str(path), local_embedding_device="cuda",
        local_embedding_batch_size=8, local_embedding_max_length=4096,
        local_embedding_normalize=True,
    )
    values.update(updates)
    return OpenAISettings(**values)


@pytest.fixture(autouse=True)
def clear_cache():
    LocalBGEM3Provider.clear_model_cache_for_tests()
    yield
    LocalBGEM3Provider.clear_model_cache_for_tests()


def test_empty_input_does_not_validate_path_or_load(tmp_path):
    calls = []
    provider = LocalBGEM3Provider(settings(tmp_path / "missing"), lambda *a: calls.append(a))
    assert provider.embed_texts([]) == []
    assert calls == []


def test_lazy_load_cache_and_encode_options(tmp_path):
    model_dir = tmp_path / "model"; model_dir.mkdir()
    model, loads = FakeModel(), []
    def loader(path, device, fp16):
        loads.append((path, device, fp16)); return model
    provider = LocalBGEM3Provider(settings(model_dir), loader, cuda_available=lambda: True)
    assert provider.embed_texts(["中", "en"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert provider.embed_texts(["again"]) == [[1.0, 0.0]]
    assert len(loads) == 1 and loads[0][1:] == ("cuda", True)
    assert model.max_seq_length == 4096
    assert model.calls[0][1] == {"batch_size": 8, "normalize_embeddings": True,
        "convert_to_numpy": True, "show_progress_bar": False}


def test_process_cache_reused_across_concurrent_providers(tmp_path):
    model_dir = tmp_path / "model"; model_dir.mkdir()
    model, count, lock = FakeModel([[1.0]]), [0], threading.Lock()
    def loader(*args):
        with lock: count[0] += 1
        return model
    providers = [LocalBGEM3Provider(settings(model_dir), loader, cuda_available=lambda: True) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda p: p.embed_texts(["x"]), providers))
    assert results == [[[1.0]]] * 8
    assert count[0] == 1


def test_cpu_requests_fp32_loader_mode(tmp_path):
    model_dir = tmp_path / "model"; model_dir.mkdir(); calls = []
    provider = LocalBGEM3Provider(settings(model_dir, local_embedding_device="cpu"),
        lambda path, device, fp16: calls.append((device, fp16)) or FakeModel([[1.0]]))
    provider.embed_texts(["x"])
    assert calls == [("cpu", False)]


def test_configured_cuda_falls_back_to_cpu_fp32_when_cuda_is_unavailable(tmp_path):
    model_dir = tmp_path / "model"; model_dir.mkdir(); calls = []
    provider = LocalBGEM3Provider(
        settings(model_dir, local_embedding_device="cuda"),
        lambda path, device, fp16: calls.append((device, fp16)) or FakeModel([[1.0]]),
        cuda_available=lambda: False,
    )
    assert provider.embed_texts(["x"]) == [[1.0]]
    assert provider.effective_device == "cpu"
    assert calls == [("cpu", False)]


def test_cuda_loader_failure_does_not_retry_cpu(tmp_path):
    model_dir = tmp_path / "model"; model_dir.mkdir(); calls = []
    def loader(path, device, fp16):
        calls.append((device, fp16))
        raise RuntimeError("cuda allocation failed")
    provider = LocalBGEM3Provider(settings(model_dir), loader, cuda_available=lambda: True)
    with pytest.raises(ContextBuildError) as error:
        provider.embed_texts(["x"])
    assert error.value.code == EMBEDDING_FAILED
    assert calls == [("cuda", True)]


@pytest.mark.parametrize("device", ["auto", "gpu", ""])
def test_invalid_device_is_configuration_error(tmp_path, device):
    model_dir = tmp_path / "model"; model_dir.mkdir()
    with pytest.raises(ContextBuildError) as error:
        LocalBGEM3Provider(settings(model_dir, local_embedding_device=device)).embed_texts(["x"])
    assert error.value.code == AI_CONFIGURATION_REQUIRED


def test_missing_model_path_is_configuration_error(tmp_path):
    with pytest.raises(ContextBuildError) as error:
        LocalBGEM3Provider(settings(tmp_path / "missing")).embed_texts(["x"])
    assert error.value.code == AI_CONFIGURATION_REQUIRED


@pytest.mark.parametrize("rows", [[], [[1.0]], [[1.0], [1.0, 2.0]], [[math.nan], [1.0]], [[True], [1.0]]])
def test_invalid_outputs_are_embedding_failures(tmp_path, rows):
    model_dir = tmp_path / "model"; model_dir.mkdir()
    provider = LocalBGEM3Provider(settings(model_dir), lambda *a: FakeModel(rows),
        cuda_available=lambda: True)
    with pytest.raises(ContextBuildError) as error:
        provider.embed_texts(["a", "b"])
    assert error.value.code == EMBEDDING_FAILED


def test_loader_errors_are_sanitized(tmp_path):
    model_dir = tmp_path / "model"; model_dir.mkdir()
    provider = LocalBGEM3Provider(settings(model_dir),
        lambda *a: (_ for _ in ()).throw(RuntimeError("secret path")),
        cuda_available=lambda: True)
    with pytest.raises(ContextBuildError) as error:
        provider.embed_texts(["x"])
    assert error.value.code == EMBEDDING_FAILED
    assert "secret" not in str(error.value)
