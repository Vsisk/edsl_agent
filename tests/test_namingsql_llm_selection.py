from types import SimpleNamespace

import pytest

from agent.context_manager.errors import ContextBuildError
from agent.context_manager.models import ContextAsset, NamingSqlCandidate
from agent.context_pack.models import ContextPack
from agent.naming_sql_selector import NamingSqlSelectRequest, NamingSqlSelector, SelectionMode
from agent.naming_sql_selector.context_adapter import NamingSqlSelectionContext
from agent.naming_sql_selector.retrieval import NamingSqlRetrievalResult


def _pack():
    return ContextPack(status="complete", request_summary={"query": "fees"}, current_node={"id": "n"})


def _request():
    return NamingSqlSelectRequest(site_id="s", project_id="p", query="fees", node={"id": "n"},
                                  json_path="$", context_pack=_pack(), top_k=2)


def _asset(asset_id):
    bo, sql = asset_id.split(":")[1:]
    return ContextAsset(asset_id=asset_id, asset_type="naming_sql", scope="global",
                        content={"bo_name": bo, "naming_sql_id": sql}, index_text=sql,
                        source="resource_registry")


def _candidate(asset_id, rank):
    bo, sql = asset_id.split(":")[1:]
    return NamingSqlCandidate(candidate_id=asset_id, bo_name=bo, naming_sql_id=sql,
                              source="resource_registry", rank=rank)


class Adapter:
    def adapt(self, pack):
        return NamingSqlSelectionContext(query_terms=["fees"], warnings=["SECTION_DEGRADED:dev_skill"])


class Retriever:
    def retrieve(self, **kwargs):
        assets = [_asset("naming_sql:Fee:a"), _asset("naming_sql:Fee:b")]
        return NamingSqlRetrievalResult(
            assets=assets,
            candidates=[_candidate(assets[0].asset_id, 1), _candidate(assets[1].asset_id, 2)],
        )


class Reranker:
    def __init__(self, selected=None, error=None):
        self.selected = selected
        self.error = error

    def rerank(self, query, assets, context):
        if self.error:
            raise self.error
        selected = self.selected if self.selected is not None else list(reversed(assets))
        return SimpleNamespace(selected_assets=selected, evidence_trace=[])


def _selector(reranker):
    return NamingSqlSelector(object(), context_adapter=Adapter(), candidate_retriever=Retriever(),
                             reranker=reranker)


def test_valid_llm_order_is_canonical_and_marks_llm_mode():
    response = _selector(Reranker()).select(_request())
    assert response.success is True
    assert response.selection_mode is SelectionMode.LLM
    assert [item.naming_sql_id for item in response.candidates] == ["b", "a"]
    assert [item.rank for item in response.candidates] == [1, 2]


@pytest.mark.parametrize("code", [
    "AI_CONFIGURATION_REQUIRED", "EMBEDDING_FAILED", "LLM_RERANK_FAILED",
    "LLM_ORGANIZER_FAILED", "INVALID_LLM_OUTPUT",
])
def test_known_ai_failure_falls_back_to_deterministic_candidates(code):
    response = _selector(Reranker(error=ContextBuildError(code, "private"))).select(_request())
    assert response.success is True
    assert response.selection_mode is SelectionMode.DETERMINISTIC_FALLBACK
    assert [item.naming_sql_id for item in response.candidates] == ["a", "b"]
    assert code in response.warnings
    assert "private" not in str(response.model_dump())


def test_unknown_duplicate_and_excessive_llm_assets_fall_back():
    original = _asset("naming_sql:Fee:a")
    variants = [
        [_asset("naming_sql:Fee:invented")],
        [original, original],
        [original, _asset("naming_sql:Fee:b"), original],
    ]
    for selected in variants:
        response = _selector(Reranker(selected=selected)).select(_request())
        assert response.selection_mode is SelectionMode.DETERMINISTIC_FALLBACK
        assert "INVALID_LLM_OUTPUT" in response.warnings


def test_unexpected_programmer_error_propagates():
    with pytest.raises(RuntimeError, match="bug"):
        _selector(Reranker(error=RuntimeError("bug"))).select(_request())
