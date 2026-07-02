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
                "requirement_hints": [], "constraints": {"allowed_bo_names": ["BO"],
                "allowed_naming_sql_aliases": ["c0001", "c0000"], "max_candidates": 2}}


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
    assert result.constraints.allowed_naming_sql_ids == ["b", "a"]
    assert "c0000" in pm.values["context_json"]
    assert '"candidate_id":"a"' not in pm.values["context_json"]


def test_context_manager_rejects_unsupported_chain_before_resolvers():
    manager = ContextManager(SimpleNamespace(), assembler=object())
    with pytest.raises(ContextBuildError) as error:
        manager.build_context(request(chain_type="expression_generation"))
    assert error.value.code == UNSUPPORTED_CONTEXT_CHAIN


@pytest.mark.parametrize("selected", [[], ["c0000"], ["c0000", "c0001", "c0002"]])
def test_organizer_must_return_exact_visible_top_k(selected):
    class BadClient:
        def complete_json(self, prompt):
            return {"selected_candidate_aliases": selected, "constraints": {}}
    with pytest.raises(ContextBuildError) as error:
        ContextPackAssembler(BadClient(), PM()).assemble(
            request(), GlobalContextBlock(), NodeContextBlock(json_path="$.x", node={}), None,
            NamingSqlResourceCandidates(candidates=[candidate("a"), candidate("b"), candidate("c")]),
            ReferenceCaseBlock(), ReferenceCaseBlock())
    assert error.value.code == "INVALID_LLM_OUTPUT"


def test_max_context_items_limits_aliases_before_render_and_selection():
    class OneClient:
        def complete_json(self, prompt):
            return {"selected_candidate_aliases": ["c0000"], "constraints": {"max_candidates": 1}}
    pm = PM()
    result = ContextPackAssembler(OneClient(), pm).assemble(
        request(max_context_items=1), GlobalContextBlock(), NodeContextBlock(json_path="$.x", node={}), None,
        NamingSqlResourceCandidates(candidates=[candidate("a"), candidate("b")]),
        ReferenceCaseBlock(), ReferenceCaseBlock())
    assert [item.candidate_id for item in result.resource_candidates.candidates] == ["a"]
    assert "c0000" in pm.values["context_json"] and "c0001" not in pm.values["context_json"]


def test_strict_and_invented_constraints_are_invalid():
    outputs = [
        {"selected_candidate_aliases": ["c0000", "c0001"], "constraints": {"max_candidates": "2"}},
        {"selected_candidate_aliases": ["c0000", "c0001"], "constraints": {"allowed_bo_names": ["invented"]}},
        {"selected_candidate_aliases": ["c0000", "c0001"], "constraints": {"allowed_naming_sql_aliases": ["c9999"]}},
    ]
    for raw in outputs:
        client = SimpleNamespace(complete_json=lambda prompt, raw=raw: raw)
        with pytest.raises(ContextBuildError) as error:
            ContextPackAssembler(client, PM()).assemble(request(), GlobalContextBlock(),
                NodeContextBlock(json_path="$.x", node={}), None,
                NamingSqlResourceCandidates(candidates=[candidate("a"), candidate("b")]),
                ReferenceCaseBlock(), ReferenceCaseBlock())
        assert error.value.code == "INVALID_LLM_OUTPUT"


def test_manager_calls_resolvers_in_fixed_order_with_prescribed_arguments():
    calls = []
    loaded = object()
    req = request()
    global_block = GlobalContextBlock()
    node_block = NodeContextBlock(json_path="$.x", node={})
    resource_block = NamingSqlResourceCandidates(candidates=[candidate("a")])
    logic_block = object()
    ootb, site = ReferenceCaseBlock(), ReferenceCaseBlock()

    class Resolver:
        def __init__(self, name, result): self.name, self.result = name, result
        def resolve(self, *args): calls.append((self.name, args)); return self.result
    class Assembler:
        def assemble(self, *args): calls.append(("assembler", args)); return "done"

    manager = ContextManager(loaded,
        Resolver("global", global_block), Resolver("edsl", node_block),
        Resolver("logic", logic_block), Resolver("resource", resource_block),
        Resolver("ootb", ootb), Resolver("site", site), Assembler())
    assert manager.build_context(req) == "done"
    assert [name for name, _ in calls] == ["global", "edsl", "logic", "resource", "ootb", "site", "assembler"]
    assert calls[1][1] == (req, loaded)
    assert calls[2][1] == (req, loaded, node_block)
    assert calls[3][1] == (req, loaded, node_block, logic_block)
    assert calls[4][1] == (req, {"node": node_block, "logic": logic_block})
    assert calls[5][1] == calls[4][1]
