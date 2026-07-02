from types import SimpleNamespace

import pytest

from agent.context_manager.errors import ContextBuildError, UNSUPPORTED_CONTEXT_CHAIN
from agent.context_manager.manager.assembler import ContextPackAssembler
from agent.context_manager.manager.context_manager import ContextManager
from agent.context_manager.models import (
    BuildContextRequest, GlobalContextBlock, NamingSqlCandidate,
    NamingSqlResourceCandidates, NodeContextBlock, ReferenceCaseBlock,
)


def candidate(cid, rank=99):
    return NamingSqlCandidate(candidate_id=cid, bo_name="BO", naming_sql_id=cid,
        source="resource_registry", rank=rank, evidence=["canonical"])


class PM:
    def render(self, key, lang="zh", **values):
        assert key == "context_namingsql_organizer"
        self.values = values
        return "prompt"


class Client:
    def complete_json(self, prompt):
        return {"selected_candidate_aliases": ["c0001", "c0000"],
                "requirement_hints": [], "constraints": {"max_candidates": 2}}


def request(**updates):
    values = dict(site_id="s", project_id="p", query="q", node={}, json_path="$.x", top_k=2)
    values.update(updates)
    return BuildContextRequest(**values)


def test_assembler_maps_opaque_aliases_and_owns_rank():
    pm = PM()
    result = ContextPackAssembler(Client(), pm).assemble(
        request(), GlobalContextBlock(), NodeContextBlock(json_path="$.x", node={}), None,
        NamingSqlResourceCandidates(candidates=[candidate("a"), candidate("b")]),
        ReferenceCaseBlock(), ReferenceCaseBlock())
    assert [item.candidate_id for item in result.resource_candidates.candidates] == ["b", "a"]
    assert [item.rank for item in result.resource_candidates.candidates] == [1, 2]
    assert result.resource_candidates.candidates[0].evidence == ["canonical"]
    assert "c0000" in pm.values["context_json"]
    assert '"candidate_id":"a"' not in pm.values["context_json"]


def test_context_manager_rejects_unsupported_chain_before_resolvers():
    manager = ContextManager(SimpleNamespace(), assembler=object())
    with pytest.raises(ContextBuildError) as error:
        manager.build_context(request(chain_type="expression_generation"))
    assert error.value.code == UNSUPPORTED_CONTEXT_CHAIN
