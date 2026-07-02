from types import SimpleNamespace

import pytest

from agent.context_manager.errors import ContextBuildError, NO_NAMING_SQL_CANDIDATES, UNSUPPORTED_CONTEXT_CHAIN
from agent.context_manager.renderers import NamingSqlContextRenderer
from agent.context_manager.resolvers import ResourceContextResolver
from agent.context_manager.manager.assembler import ContextPackAssembler
from agent.context_manager.manager.context_manager import ContextManager
from agent.context_manager.models import (
    BuildContextRequest, ContextAsset, GlobalContextBlock, NamingSqlCandidate,
    NamingSqlResourceCandidates, NodeContextBlock, ReferenceCaseBlock,
    ReferenceCaseCandidate,
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


def test_zero_candidates_fails_before_organizer_call():
    client = SimpleNamespace(complete_json=lambda prompt: pytest.fail("must not call organizer"))
    with pytest.raises(ContextBuildError) as error:
        ContextPackAssembler(client, PM()).assemble(request(), GlobalContextBlock(),
            NodeContextBlock(json_path="$.x", node={}), None, NamingSqlResourceCandidates(),
            ReferenceCaseBlock(), ReferenceCaseBlock())
    assert error.value.code == NO_NAMING_SQL_CANDIDATES


@pytest.mark.parametrize("aliases", [["c0000", "c0000"], ["c0000", "c9999"]])
def test_duplicate_and_invented_selected_aliases_are_invalid(aliases):
    client = SimpleNamespace(complete_json=lambda prompt: {
        "selected_candidate_aliases": aliases, "constraints": {"max_candidates": 2}})
    with pytest.raises(ContextBuildError) as error:
        ContextPackAssembler(client, PM()).assemble(request(), GlobalContextBlock(),
            NodeContextBlock(json_path="$.x", node={}), None,
            NamingSqlResourceCandidates(candidates=[candidate("a"), candidate("b")]),
            ReferenceCaseBlock(), ReferenceCaseBlock())
    assert error.value.code == "INVALID_LLM_OUTPUT"


def test_more_than_forty_budgeted_candidates_have_no_hidden_aliases():
    many = [candidate(f"id-{index}") for index in range(45)]
    class LastClient:
        def complete_json(self, prompt):
            return {"selected_candidate_aliases": ["c0044"], "constraints": {"max_candidates": 1}}
    pm = PM()
    result = ContextPackAssembler(LastClient(), pm).assemble(
        request(top_k=1, max_context_items=45), GlobalContextBlock(),
        NodeContextBlock(json_path="$.x", node={}), None,
        NamingSqlResourceCandidates(candidates=many), ReferenceCaseBlock(), ReferenceCaseBlock())
    assert result.resource_candidates.candidates[0].candidate_id == "id-44"
    assert all(f'"alias":"c{index:04d}"' in pm.values["context_json"] for index in range(45))


def test_renderer_is_deterministic_bounded_and_strips_sql_bodies():
    renderer = NamingSqlContextRenderer()
    req = request(node={"sql_command": "SECRET", "text": "汉" * 50000})
    kwargs = dict(request=req, global_context=GlobalContextBlock(),
        node_context=NodeContextBlock(json_path="$.x", node=req.node), logic_area_context=None,
        resource_candidates=NamingSqlResourceCandidates(), ootb_reference_cases=ReferenceCaseBlock(),
        site_knowledge_cases=ReferenceCaseBlock(), candidate_aliases={}, reference_aliases={})
    first = renderer.render(**kwargs)
    assert first == renderer.render(**kwargs)
    assert len(first) <= renderer.max_total_chars and "SECRET" not in first


def test_constraints_cannot_reference_visible_but_unselected_candidate():
    client = SimpleNamespace(complete_json=lambda prompt: {
        "selected_candidate_aliases": ["c0000", "c0001"],
        "constraints": {"allowed_naming_sql_aliases": ["c0002"], "max_candidates": 2}})
    with pytest.raises(ContextBuildError) as error:
        ContextPackAssembler(client, PM()).assemble(request(), GlobalContextBlock(),
            NodeContextBlock(json_path="$.x", node={}), None,
            NamingSqlResourceCandidates(candidates=[candidate("a"), candidate("b"), candidate("c")]),
            ReferenceCaseBlock(), ReferenceCaseBlock())
    assert error.value.code == "INVALID_LLM_OUTPUT"


def test_reference_hint_evidence_are_canonicalized_and_debug_is_opt_in():
    ref = ReferenceCaseCandidate(asset=ContextAsset(asset_id="ootb_case:one",
        asset_type="ootb_case", scope="global", content={}, index_text="one"))
    raw = {"selected_candidate_aliases": ["c0000"],
        "retained_reference_aliases": ["r0000"],
        "requirement_hints": [{"semantic_name": "id", "bind_to_candidates": ["c0000", "r0000"]}],
        "evidence_trace": [{"source": "organizer", "action": "selected", "asset_id": "r0000", "evidence": "match"}],
        "constraints": {"allowed_naming_sql_aliases": ["c0000"], "max_candidates": 1}}
    client = SimpleNamespace(complete_json=lambda prompt: raw)
    args = (GlobalContextBlock(), NodeContextBlock(json_path="$.x", node={}), None,
        NamingSqlResourceCandidates(candidates=[candidate("a")]),
        ReferenceCaseBlock(candidates=[ref]), ReferenceCaseBlock())
    normal = ContextPackAssembler(client, PM()).assemble(request(top_k=1), *args)
    debug = ContextPackAssembler(client, PM()).assemble(request(top_k=1, debug=True), *args)
    assert normal.prompt_view is None and debug.prompt_view is not None
    assert normal.requirement_hints[0].bind_to_candidates == ["a", "ootb_case:one"]
    assert normal.ootb_reference_cases.candidates[0].asset.asset_id == "ootb_case:one"
    assert normal.evidence_trace[-1].asset_id == "ootb_case:one"


def test_resource_candidate_retains_enriched_structured_return_information_without_rank():
    asset = ContextAsset(asset_id="naming_sql:BO:sql.one", asset_type="naming_sql",
        scope="global", index_text="candidate", content={"bo_name": "BO",
        "naming_sql_id": "sql.one", "return_information": [{"field_name": "amount", "data_type_name": "decimal"}]})
    result = ResourceContextResolver._candidate(asset)
    assert result.return_type == {"fields": [{"field_name": "amount", "data_type_name": "decimal"}]}
    assert result.rank == 0


def test_forty_oversized_rows_keep_essential_facts_under_global_cap():
    renderer = NamingSqlContextRenderer()
    items = [NamingSqlCandidate(candidate_id=f"id{i}", bo_name=f"BO{i}", naming_sql_id=f"sql{i}",
        naming_sql_name=f"name{i}", annotation="x" * 10000,
        param_list=[{"param_name": f"p{i}", "data_type_name": "string", "junk": "y" * 10000}],
        return_type={"type": "row", "junk": "z" * 10000}, source="resource_registry", rank=0,
        evidence=["e" * 10000]) for i in range(40)]
    visible, refs = renderer.budget_inputs(items, [], 40)
    aliases = {f"c{i:04d}": item for i, item in enumerate(visible)}
    text = renderer.render(request=request(top_k=20), global_context=GlobalContextBlock(),
        node_context=NodeContextBlock(json_path="$.x", node={}), logic_area_context=None,
        resource_candidates=NamingSqlResourceCandidates(candidates=visible),
        ootb_reference_cases=ReferenceCaseBlock(), site_knowledge_cases=ReferenceCaseBlock(),
        candidate_aliases=aliases, reference_aliases={})
    assert len(visible) == 40 and len(text) <= renderer.max_total_chars
    for i in range(40):
        assert all(value in text for value in (f"c{i:04d}", f"BO{i}", f"sql{i}", f"name{i}", f"p{i}", "string"))


def test_hint_evidence_unknown_alias_and_context_path_are_invalid():
    bad_parts = [
        {"evidence": [{"source": "x", "action": "x", "asset_id": "raw-id", "evidence": "x"}]},
        {"candidate_context_paths": ["$ctx$.invented"]},
    ]
    for extra in bad_parts:
        hint = {"semantic_name": "id", **extra}
        client = SimpleNamespace(complete_json=lambda prompt, hint=hint: {
            "selected_candidate_aliases": ["c0000"], "requirement_hints": [hint],
            "constraints": {"max_candidates": 1}})
        with pytest.raises(ContextBuildError) as error:
            ContextPackAssembler(client, PM()).assemble(request(top_k=1), GlobalContextBlock(),
                NodeContextBlock(json_path="$.x", node={}), None,
                NamingSqlResourceCandidates(candidates=[candidate("a")]),
                ReferenceCaseBlock(), ReferenceCaseBlock())
        assert error.value.code == "INVALID_LLM_OUTPUT"


def test_shared_reference_instance_retains_only_selected_occurrence():
    shared = ReferenceCaseCandidate(asset=ContextAsset(asset_id="ootb_case:shared",
        asset_type="ootb_case", scope="global", content={}, index_text="shared"))
    client = SimpleNamespace(complete_json=lambda prompt: {"selected_candidate_aliases": ["c0000"],
        "retained_reference_aliases": ["r0001"], "constraints": {"max_candidates": 1}})
    result = ContextPackAssembler(client, PM()).assemble(request(top_k=1, max_context_items=3),
        GlobalContextBlock(), NodeContextBlock(json_path="$.x", node={}), None,
        NamingSqlResourceCandidates(candidates=[candidate("a")]),
        ReferenceCaseBlock(candidates=[shared]), ReferenceCaseBlock(candidates=[shared]))
    assert result.ootb_reference_cases.candidates == []
    assert result.site_knowledge_cases.candidates == [shared]
