import hashlib

import pytest

from agent.context_pack.errors import SOURCE_UNAVAILABLE, STALE_SOURCE, ContextProviderError
from agent.context_pack.models import SearchDocument, SourceLocator
from agent.context_pack.search import IndexCache, LocalResourceSearchTool, reciprocal_rank_fusion


def document(item_id, text, *, name=None, path=None):
    return SearchDocument(
        item_id=item_id,
        source_id="skill",
        item_type="recipe",
        search_text=text,
        summary=name or text,
        locator=SourceLocator(source_id="skill", kind="line_range", value=item_id, path=path),
        authority="normative",
        content_hash="hash",
        content={"name": name or item_id},
    )


class FakeEmbeddingClient:
    def __init__(self, vectors=None, error=None):
        self.vectors = vectors or []
        self.error = error
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(texts)
        if self.error:
            raise self.error
        return self.vectors[: len(texts)]


def test_reciprocal_rank_fusion_is_stable_for_ties():
    assert reciprocal_rank_fusion([["b", "a"], ["a", "b"]], ["a", "b"]) == ["a", "b"]


def test_exact_hit_is_pinned_before_lexical_and_semantic_hits():
    docs = [document("customer.full_name", "unrelated"), document("other", "customer full name")]
    fake = FakeEmbeddingClient([[1, 0], [0, 1], [1, 0]])
    tool = LocalResourceSearchTool(fake)
    tool.register_source("skill", docs)

    result = tool.search("skill", "customer.full_name", limit=2)

    assert [hit.document.item_id for hit in result.hits][0] == "customer.full_name"
    assert result.hits[0].evidence[0].match_kind == "exact"


def test_embedding_failure_returns_lexical_hits_as_degraded():
    tool = LocalResourceSearchTool(FakeEmbeddingClient(error=RuntimeError("offline secret")))
    tool.register_source("skill", [document("name", "customer full name")])

    result = tool.search("skill", "customer name", limit=3)

    assert [hit.document.item_id for hit in result.hits] == ["name"]
    assert result.degraded is True
    assert result.warnings == ["embedding unavailable"]


def test_unknown_source_id_is_rejected():
    with pytest.raises(ContextProviderError) as error:
        LocalResourceSearchTool().search("missing", "query", limit=1)
    assert error.value.code == SOURCE_UNAVAILABLE


def test_read_slice_rejects_stale_hash_and_path_traversal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    source = root / "skill.md"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    tool = LocalResourceSearchTool()
    tool.register_source("skill", [], root=root)
    locator = SourceLocator(
        source_id="skill", kind="line_range", value="slice", path="skill.md", start_line=2, end_line=3
    )
    expected = hashlib.sha256("two\nthree\n".encode()).hexdigest()

    assert tool.read_slice(locator, expected) == "two\nthree\n"
    with pytest.raises(ContextProviderError) as stale:
        tool.read_slice(locator, "bad")
    assert stale.value.code == STALE_SOURCE
    escaped = locator.model_copy(update={"path": "../outside.md"})
    with pytest.raises(ContextProviderError):
        tool.read_slice(escaped, expected)


def test_lru_cache_key_includes_all_versions_and_evicts_oldest():
    cache = IndexCache(max_entries=1)
    first = cache.get_or_build(("s", "v1", "p1", "m1"), lambda: ["one"])
    second = cache.get_or_build(("s", "v2", "p1", "m1"), lambda: ["two"])

    assert first == ("one",) and second == ("two",)
    assert cache.get(("s", "v1", "p1", "m1")) is None
