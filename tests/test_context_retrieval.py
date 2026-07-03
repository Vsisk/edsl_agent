from types import SimpleNamespace

import pytest

from agent.context_manager.errors import AI_CONFIGURATION_REQUIRED, EMBEDDING_FAILED, ContextBuildError
from agent.context_manager.models import ContextAsset
from agent.context_manager.retrieval import EmbeddingClient, HybridRetriever, LexicalRetriever, SemanticRetriever
from agent.llm.config import OpenAISettings, load_openai_settings


def asset(asset_id, index_text, content=None, metadata=None):
    return ContextAsset(
        asset_id=asset_id,
        asset_type="naming_sql",
        scope="project",
        content=content or {},
        index_text=index_text,
        metadata=metadata or {},
    )


class FakeEmbeddings:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(texts)
        return self.vectors[: len(texts)]


def test_hybrid_returns_semantic_then_unseen_exact_without_mutation():
    assets = [
        asset("semantic", "customer lookup", {"name": "customerLookup"}, {"kept": True}),
        asset("exact", "unrelated", {"naming_sql_name": "findInvoice"}),
    ]
    fake = FakeEmbeddings([[1, 0], [1, 0], [0, 1]])

    result = HybridRetriever(fake).retrieve("findInvoice", assets, semantic_limit=1)

    assert [item.asset_id for item in result] == ["semantic", "exact"]
    assert result[0].metadata == {"kept": True, "embedding_similarity": 1.0}
    assert "embedding_similarity" not in assets[0].metadata
    assert result[0] is not assets[0]


def test_hybrid_deduplicates_exact_asset_already_recalled_semantically():
    assets = [asset("same", "findInvoice", {"name": "findInvoice"})]
    result = HybridRetriever(FakeEmbeddings([[1], [1]])).retrieve("findInvoice", assets, semantic_limit=1)
    assert [item.asset_id for item in result] == ["same"]


def test_semantic_ties_preserve_original_order_and_zero_vectors_are_safe():
    assets = [asset("first", "a"), asset("second", "b")]
    result = SemanticRetriever(FakeEmbeddings([[0, 0], [0, 0], [0, 0]])).retrieve("q", assets, limit=2)
    assert [item.asset_id for item in result] == ["first", "second"]
    assert [item.metadata["embedding_similarity"] for item in result] == [0.0, 0.0]


@pytest.mark.parametrize(
    "vector",
    [
        [1.0e308, 1.0e308],
        [1.0e-308, 1.0e-308],
    ],
)
def test_semantic_cosine_is_stable_for_huge_and_tiny_parallel_vectors(vector):
    result = SemanticRetriever(FakeEmbeddings([vector, vector])).retrieve(
        "q", [asset("parallel", "parallel")], limit=1
    )
    assert result[0].metadata["embedding_similarity"] == pytest.approx(1.0)


def test_semantic_rejects_boolean_embedding_values():
    with pytest.raises(ContextBuildError) as error:
        SemanticRetriever(FakeEmbeddings([[True, 0.0], [1.0, 0.0]])).retrieve(
            "q", [asset("a", "a")], limit=1
        )
    assert error.value.code == EMBEDDING_FAILED


@pytest.mark.parametrize("vectors", [[], [[1]], [[1], [1, 2]]])
def test_semantic_rejects_invalid_embedding_shapes(vectors):
    with pytest.raises(ContextBuildError) as error:
        SemanticRetriever(FakeEmbeddings(vectors)).retrieve("q", [asset("a", "a")], limit=1)
    assert error.value.code == EMBEDDING_FAILED


def test_retrievers_return_empty_without_embedding_call():
    fake = FakeEmbeddings([])
    assert SemanticRetriever(fake).retrieve("q", [], limit=3) == []
    assert HybridRetriever(fake).retrieve("q", []) == []
    assert fake.calls == []


def test_hybrid_deduplicates_duplicate_ids_within_semantic_and_lexical_streams():
    assets = [
        asset("duplicate", "first", {"name": "findInvoice"}),
        asset("duplicate", "second", {"name": "findInvoice"}),
        asset("exact", "third", {"name": "findInvoice"}),
    ]
    fake = FakeEmbeddings([[1, 0], [1, 0], [0.9, 0.1], [0, 1]])

    result = HybridRetriever(fake).retrieve("findInvoice", assets, semantic_limit=2)

    assert [item.asset_id for item in result] == ["duplicate", "exact"]


def test_hybrid_deduplicates_duplicate_ids_when_only_lexical_recall_runs():
    assets = [
        asset("duplicate", "first", {"name": "findInvoice"}),
        asset("duplicate", "second", {"name": "findInvoice"}),
    ]

    result = HybridRetriever(FakeEmbeddings([])).retrieve("findInvoice", assets, semantic_limit=0)

    assert [item.asset_id for item in result] == ["duplicate"]


def test_lexical_matches_stable_id_and_nested_useful_names_in_original_order():
    assets = [
        asset("sql.invoice", "other", {"params": [{"field_name": "accountId"}]}),
        asset("accountId", "other"),
        asset("miss", "other"),
    ]
    assert [a.asset_id for a in LexicalRetriever().retrieve("account id", assets)] == [
        "sql.invoice", "accountId"
    ]


def test_embedding_client_uses_settings_order_and_empty_short_circuit():
    settings = OpenAISettings(True, "key", "https://example.test", "base", "vl", 7, "embed", "openai")
    client = EmbeddingClient(settings)
    calls = []
    client._client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(
                data=[SimpleNamespace(index=1, embedding=[2.0]), SimpleNamespace(index=0, embedding=[1.0])]
            )
        )
    )
    assert client.embed_texts([]) == []
    assert client.embed_texts(["a", "b"]) == [[1.0], [2.0]]
    assert calls == [{"model": "embed", "input": ["a", "b"]}]


def test_embedding_client_configuration_and_provider_failures_are_sanitized():
    unusable = OpenAISettings(False, "secret", None, "base", "vl", 3, embedding_provider="openai")
    with pytest.raises(ContextBuildError) as config_error:
        EmbeddingClient(unusable).embed_texts(["x"])
    assert config_error.value.code == AI_CONFIGURATION_REQUIRED

    usable = OpenAISettings(True, "secret", None, "base", "vl", 3, embedding_provider="openai")
    client = EmbeddingClient(usable)
    client._client = SimpleNamespace(
        embeddings=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret leaked")))
    )
    with pytest.raises(ContextBuildError) as provider_error:
        client.embed_texts(["x"])
    assert provider_error.value.code == EMBEDDING_FAILED
    assert "secret" not in str(provider_error.value)


def test_embedding_client_rejects_duplicate_response_indexes():
    settings = OpenAISettings(True, "key", None, "base", "vl", 3, embedding_provider="openai")
    client = EmbeddingClient(settings)
    client._client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                data=[SimpleNamespace(index=0, embedding=[1.0]), SimpleNamespace(index=0, embedding=[2.0])]
            )
        )
    )
    with pytest.raises(ContextBuildError) as error:
        client.embed_texts(["a", "b"])
    assert error.value.code == EMBEDDING_FAILED


def test_openai_settings_constructor_compatibility_and_embedding_env(tmp_path):
    legacy = OpenAISettings(True, "key", None, "base", "vl", 30)
    assert legacy.embedding_model == "bge-m3"
    assert legacy.embedding_provider == "local_bge_m3"
    assert legacy.local_embedding_model_path == r"D:\models\bge-m3"
    assert legacy.local_embedding_device == "cuda"
    assert legacy.local_embedding_batch_size == 8
    assert legacy.local_embedding_max_length == 4096
    assert legacy.local_embedding_normalize is True
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_EMBEDDING_MODEL=custom-embed\n"
        "EMBEDDING_PROVIDER=openai\n"
        "LOCAL_EMBEDDING_MODEL_PATH=X:\\models\\custom\n"
        "LOCAL_EMBEDDING_DEVICE=cpu\n"
        "LOCAL_EMBEDDING_BATCH_SIZE=3\n"
        "LOCAL_EMBEDDING_MAX_LENGTH=512\n"
        "LOCAL_EMBEDDING_NORMALIZE=false\n",
        encoding="utf-8",
    )
    settings = load_openai_settings(env)
    assert settings.embedding_model == "custom-embed"
    assert settings.embedding_provider == "openai"
    assert settings.local_embedding_model_path == r"X:\models\custom"
    assert settings.local_embedding_device == "cpu"
    assert settings.local_embedding_batch_size == 3
    assert settings.local_embedding_max_length == 512
    assert settings.local_embedding_normalize is False
