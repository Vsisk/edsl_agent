import pytest

from agent.context_manager.errors import ContextBuildError, INVALID_LLM_OUTPUT, LLM_RERANK_FAILED
from agent.context_manager.models import ContextAsset
from agent.context_manager.retrieval import (
    LLMReranker, MAX_ASSET_CANDIDATES, MAX_ASSET_SUMMARY_CHARS,
    MAX_CONTEXT_CHARS, MAX_QUERY_CHARS,
)


def asset(asset_id, summary="semantic summary", content=None):
    return ContextAsset(asset_id=asset_id, asset_type="naming_sql", scope="project", content=content or {}, index_text=summary)


class Client:
    def __init__(self, output=None, error=None): self.output, self.error, self.calls = output, error, []
    def complete_json(self, prompt):
        self.calls.append(prompt)
        if self.error: raise self.error
        return self.output


class Prompts:
    def __init__(self): self.calls = []
    def render(self, key, lang="zh", **variables):
        self.calls.append((key, lang, variables))
        return "PROMPT\n" + "\n".join(variables.values())


def valid(ids):
    return {"selected_asset_ids": ids, "rejected_assets": [{"asset_id": "b", "reason": "less relevant"}], "context_requirement_hints": [{"semantic_name": "customer id", "bind_to_candidates": ids}], "evidence_trace": [{"source": "llm_reranker", "action": "select", "asset_id": ids[0] if ids else None, "evidence": "query match", "payload": {}}]}


def test_reranker_preserves_llm_order_hints_evidence_and_calls_once():
    client, prompts = Client(valid(["b", "a"])), Prompts()
    result = LLMReranker(client=client, prompt_manager=prompts).rerank("find customer", [asset("a"), asset("b")], {"bo": "Customer"})
    assert [a.asset_id for a in result.selected_assets] == ["b", "a"]
    assert result.rejected_assets[0]["asset_id"] == "b"
    assert result.context_requirement_hints[0].semantic_name == "customer id"
    assert result.evidence_trace[0].action == "select"
    assert len(client.calls) == 1 and prompts.calls[0][0] == "context_namingsql_reranker"


def test_reranker_accepts_minimal_reply_and_defaults_auxiliary_lists():
    result = LLMReranker(Client({"selected_asset_ids": ["a"]}), Prompts()).rerank("q", [asset("a")], {})
    assert [item.asset_id for item in result.selected_assets] == ["a"]
    assert result.rejected_assets == []
    assert result.context_requirement_hints == []
    assert result.evidence_trace == []


@pytest.mark.parametrize("ids", [["unknown"], ["a", "a"]])
def test_reranker_rejects_unknown_or_duplicate_selected_ids(ids):
    with pytest.raises(ContextBuildError) as error:
        LLMReranker(Client(valid(ids)), Prompts()).rerank("q", [asset("a")], {})
    assert error.value.code == INVALID_LLM_OUTPUT


@pytest.mark.parametrize("output", [{}, {"selected_asset_ids": [], "rejected_assets": [], "context_requirement_hints": [], "evidence_trace": [], "extra": 1}, "bad"])
def test_reranker_rejects_malformed_schema(output):
    with pytest.raises(ContextBuildError) as error:
        LLMReranker(Client(output), Prompts()).rerank("q", [asset("a")], {})
    assert error.value.code == INVALID_LLM_OUTPUT


@pytest.mark.parametrize(
    "output",
    [
        {"selected_asset_ids": [1]},
        {"selected_asset_ids": [], "rejected_assets": "not-a-list"},
        {"selected_asset_ids": [], "rejected_assets": ["not-an-object"]},
        {"selected_asset_ids": [], "context_requirement_hints": [1]},
        {"selected_asset_ids": [], "evidence_trace": [1]},
    ],
)
def test_reranker_maps_non_strict_or_wrong_container_types_to_invalid_output(output):
    with pytest.raises(ContextBuildError) as error:
        LLMReranker(Client(output), Prompts()).rerank("q", [asset("a")], {})
    assert error.value.code == INVALID_LLM_OUTPUT


def test_reranker_wraps_client_failure():
    with pytest.raises(ContextBuildError) as error:
        LLMReranker(Client(error=RuntimeError("secret")), Prompts()).rerank("q", [asset("a")], {})
    assert error.value.code == LLM_RERANK_FAILED and "secret" not in str(error.value)


def test_prompt_is_bounded_and_never_contains_sql_command():
    client, prompts = Client({"selected_asset_ids": [], "rejected_assets": [], "context_requirement_hints": [], "evidence_trace": []}), Prompts()
    assets = [asset(str(i), "x" * 10000, {"sql_command": "DO NOT LEAK"}) for i in range(MAX_ASSET_CANDIDATES + 5)]
    LLMReranker(client, prompts).rerank("q" * (MAX_QUERY_CHARS + 99), assets, {"sql_command": "CONTEXT LEAK", "notes": "z" * 10000})
    prompt = client.calls[0]
    assert "DO NOT LEAK" not in prompt
    assert "CONTEXT LEAK" not in prompt
    variables = prompts.calls[0][2]
    assert len(variables["query"]) == MAX_QUERY_CHARS
    assert len(variables["context_json"]) == MAX_CONTEXT_CHARS
    assert len(__import__("json").loads(variables["candidates_json"])) == MAX_ASSET_CANDIDATES
    assert all(len(item["semantic_summary"]) == MAX_ASSET_SUMMARY_CHARS for item in __import__("json").loads(variables["candidates_json"]))
