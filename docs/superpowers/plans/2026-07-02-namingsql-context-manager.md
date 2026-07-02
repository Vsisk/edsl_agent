# NamingSQL Context Manager Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deterministic single-SQL selector with a Context Manager that uses embedding recall and LLM reranking/organization to return an authoritative ordered Top-K NamingSQL set for the planner.

**Architecture:** Existing `LoadedResource` registries remain authoritative. Focused resolvers adapt them to `ContextAsset`, hybrid retrieval creates bounded candidate unions, and strict LLM stages select and organize the final Top-K. `NamingSqlSelector` is reduced to a request/response facade; `ValueLogicGenerator` routes successful Top-K responses into the planner, whose validator forbids out-of-set NamingSQL.

**Tech Stack:** Python 3.10+, Pydantic v2, OpenAI Python SDK, `jsonpath-ng`, `unittest`/pytest-compatible tests.

---

## File Structure

Create these focused modules:

- `agent/context_manager/models/request.py`: context request and chain enum.
- `agent/context_manager/models/assets.py`: normalized asset, candidate, and evidence models.
- `agent/context_manager/models/context.py`: resolver blocks and internal selection context.
- `agent/context_manager/retrieval/embedding_client.py`: replaceable embedding protocol and OpenAI-compatible adapter.
- `agent/context_manager/retrieval/lexical.py`: exact-match supplementation only.
- `agent/context_manager/retrieval/semantic.py`: cosine-based embedding recall.
- `agent/context_manager/retrieval/hybrid.py`: stable candidate union without final scoring.
- `agent/context_manager/retrieval/llm_reranker.py`: strict candidate-ID selection.
- `agent/context_manager/resolvers/global_context.py`: required global and chain rules.
- `agent/context_manager/resolvers/edsl_project.py`: EDSL structural context.
- `agent/context_manager/resolvers/logic_area.py`: referenced or recalled logic-area context.
- `agent/context_manager/resolvers/resource.py`: registry-to-asset conversion and resource reranking.
- `agent/context_manager/resolvers/reference_cases.py`: OOTB and site/history JSONL cases.
- `agent/context_manager/renderers/naming_sql_context.py`: organizer prompt rendering.
- `agent/context_manager/manager/assembler.py`: strict organizer validation and context assembly.
- `agent/context_manager/manager/context_manager.py`: fixed-order orchestration.
- `agent/context_manager/errors.py`: stable domain failure codes.
- `agent/context_manager/__init__.py` and package `__init__.py` files: narrow public exports.
- `agent_rules/GLOBAL.md` and `agent_rules/chains/namingsql_selection.md`: required long-lived rules.
- `agent/context_manager/mock_data/*.jsonl`: empty valid enhancement corpora initially.

Replace or modify:

- `agent/naming_sql_selector/models.py`: new Top-K public contracts.
- `agent/naming_sql_selector/selector.py`: facade only.
- `agent/naming_sql_selector/__init__.py`: new exports only.
- `agent/resource_manager/loader/resource_loader.py`: remove old profile-cache dependency.
- `agent/environment/environment.py`: store `NamingSqlSelectResponse`.
- `agent/value_logic_generator.py`: create a request-scoped selector from the current `LoadedResource`, invoke it, and stop on failure.
- `agent/planner/llm_planner.py`: expose only Top-K candidates to the planner.
- `agent/naming_sql_selector/plan_validator.py`: validate membership and parameter names rather than fixed selection.
- `prompt.json`: add reranker and organizer prompts.

Delete after callers migrate:

- `agent/naming_sql_selector/knowledge.py`
- `agent/naming_sql_selector/profile_builder.py`
- `agent/naming_sql_selector/spec_generator.py`

Replace old selector tests and add:

- `tests/test_context_models.py`
- `tests/test_context_asset_builder.py`
- `tests/test_context_retrieval.py`
- `tests/test_context_resolvers.py`
- `tests/test_llm_reranker_contract.py`
- `tests/test_context_manager_namingsql.py`
- `tests/test_namingsql_selector_context_request.py`

## Task 1: Establish Contracts, Rules, and Failure Codes

**Files:**
- Create: `agent/context_manager/errors.py`
- Create: `agent/context_manager/models/request.py`
- Create: `agent/context_manager/models/assets.py`
- Create: `agent/context_manager/models/context.py`
- Create: `agent/context_manager/models/__init__.py`
- Create: `agent_rules/GLOBAL.md`
- Create: `agent_rules/chains/namingsql_selection.md`
- Test: `tests/test_context_models.py`

- [ ] **Step 1: Write failing model-contract tests**

```python
from pydantic import ValidationError

from agent.context_manager.models import BuildContextRequest, NamingSqlCandidate


def test_build_context_request_bounds_top_k_and_defaults_chain():
    request = BuildContextRequest(
        site_id="s", project_id="p", query="fee", node={}, json_path="$.nodes[0]"
    )
    assert request.chain_type == "namingsql_selection"
    assert request.top_k == 5
    for invalid in (0, 21):
        try:
            request.model_copy(update={"top_k": invalid}).__class__.model_validate(
                {**request.model_dump(), "top_k": invalid}
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("invalid top_k accepted")


def test_candidate_has_no_final_score_field():
    assert "score" not in NamingSqlCandidate.model_fields
    assert "rank" in NamingSqlCandidate.model_fields
```

- [ ] **Step 2: Run the tests and observe missing modules**

Run: `python -m pytest tests/test_context_models.py -q`

Expected: FAIL during import with `ModuleNotFoundError: No module named 'agent.context_manager'`.

- [ ] **Step 3: Add strict Pydantic contracts and stable errors**

Implement `BuildContextRequest` with `chain_type`, `max_context_items=50`, and `top_k=Field(5, ge=1, le=20)`. Implement `ContextAsset`, `ContextEvidenceItem`, `NamingSqlCandidate`, `ContextRequirementHint`, `NamingSqlSelectionConstraints`, resolver block models, and `NamingSqlSelectionContext` using `ConfigDict(extra="forbid")`. Use this exact error base:

```python
class ContextBuildError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)
```

Define stable codes as constants: `AI_CONFIGURATION_REQUIRED`, `EMBEDDING_FAILED`, `LLM_RERANK_FAILED`, `LLM_ORGANIZER_FAILED`, `INVALID_LLM_OUTPUT`, `RULE_FILE_MISSING`, `EDSL_NODE_NOT_FOUND`, `UNSUPPORTED_CONTEXT_CHAIN`, and `NO_NAMING_SQL_CANDIDATES`.

- [ ] **Step 4: Add required rule files**

`GLOBAL.md` states that only loaded resources may be returned, evidence must be retained, and expressions/resources must not be invented. `namingsql_selection.md` states that output is an ordered Top-K, final ordering is LLM-owned, and planner consumption is restricted to that set.

- [ ] **Step 5: Run the contract tests**

Run: `python -m pytest tests/test_context_models.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the contracts**

```bash
git add agent/context_manager agent_rules tests/test_context_models.py
git commit -m "feat: add context manager contracts"
```

## Task 2: Add the Embedding Adapter and Hybrid Recall

**Files:**
- Create: `agent/context_manager/retrieval/embedding_client.py`
- Create: `agent/context_manager/retrieval/lexical.py`
- Create: `agent/context_manager/retrieval/semantic.py`
- Create: `agent/context_manager/retrieval/hybrid.py`
- Create: `agent/context_manager/retrieval/__init__.py`
- Modify: `agent/llm/config.py`
- Test: `tests/test_context_retrieval.py`

- [ ] **Step 1: Write failing recall tests with fake embeddings**

```python
from agent.context_manager.models import ContextAsset
from agent.context_manager.retrieval import HybridRetriever


class FakeEmbeddingClient:
    def embed_texts(self, texts):
        vectors = {"fee": [1.0, 0.0], "charge sql": [0.9, 0.1], "exact_bo": [0.0, 1.0]}
        return [vectors.get(text, [0.0, 1.0]) for text in texts]


def test_hybrid_recall_unions_semantic_and_exact_without_final_score():
    assets = [
        ContextAsset(asset_id="semantic", asset_type="naming_sql", scope="site", content={}, index_text="charge sql"),
        ContextAsset(asset_id="exact", asset_type="bo", scope="site", content={"bo_name": "EXACT_BO"}, index_text="unrelated"),
    ]
    result = HybridRetriever(FakeEmbeddingClient()).retrieve("fee EXACT_BO", assets, semantic_limit=1)
    assert [item.asset_id for item in result] == ["semantic", "exact"]
```

- [ ] **Step 2: Run the recall test and verify failure**

Run: `python -m pytest tests/test_context_retrieval.py -q`

Expected: FAIL because retrieval modules do not exist.

- [ ] **Step 3: Implement only the missing embedding protocol and configuration**

Reuse `agent.llm.LLMClient`, `generate_by_llm`, `PromptManager`, and JSON post-processing unchanged for all LLM calls. Add `embedding_model` to `OpenAISettings`, loaded from `OPENAI_EMBEDDING_MODEL`, and implement only the missing embedding protocol:

```python
class EmbeddingClientProtocol(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
```

The production embedding adapter lazily creates `OpenAI`, rejects unusable settings with `ContextBuildError("AI_CONFIGURATION_REQUIRED")`, and calls `client.embeddings.create(model=settings.embedding_model, input=texts)`. Reranker and organizer tests inject fakes compatible with the existing `LLMClient.complete_json(prompt)` method.

- [ ] **Step 4: Implement retrieval without aggregate final scoring**

`SemanticRetriever` computes cosine similarity and returns Top-N with similarity stored in copied `metadata`. `LexicalRetriever` returns assets whose names, IDs, fields, or parameters exactly match normalized query terms. `HybridRetriever` appends semantic results first and then unseen lexical results; it does not calculate or sort by a combined score.

- [ ] **Step 5: Run retrieval and existing config tests**

Run: `python -m pytest tests/test_context_retrieval.py tests/test_llm_integration.py -q`

Expected: PASS.

- [ ] **Step 6: Commit AI boundaries and recall**

```bash
git add agent/context_manager/retrieval agent/llm/config.py tests/test_context_retrieval.py
git commit -m "feat: add embedding context recall"
```

## Task 3: Build Semantic Assets and Resource Reranking

**Files:**
- Create: `agent/context_manager/resolvers/resource.py`
- Create: `agent/context_manager/retrieval/llm_reranker.py`
- Modify: `prompt.json`
- Test: `tests/test_context_asset_builder.py`
- Test: `tests/test_llm_reranker_contract.py`

- [ ] **Step 1: Write failing asset and reranker tests**

```python
def test_naming_sql_asset_text_is_semantic(resource_asset_builder, naming_sql_definition):
    asset = resource_asset_builder.naming_sql("BO_CHARGE", naming_sql_definition)
    assert "BO BO_CHARGE" in asset.index_text
    assert naming_sql_definition.sql_name in asset.index_text
    assert naming_sql_definition.param_list[0].param_name in asset.index_text
    assert not asset.index_text.lstrip().startswith("{")


def test_reranker_rejects_invented_asset_id(reranker, naming_sql_asset):
    reranker.llm.reply = {"selected_asset_ids": ["invented"]}
    with pytest.raises(ContextBuildError, match="INVALID_LLM_OUTPUT"):
        reranker.rerank(query="fee", assets=[naming_sql_asset], context={})
```

- [ ] **Step 2: Run tests and verify missing builder/reranker failures**

Run: `python -m pytest tests/test_context_asset_builder.py tests/test_llm_reranker_contract.py -q`

Expected: FAIL because `ResourceAssetBuilder` and `LLMReranker` do not exist.

- [ ] **Step 3: Implement type-specific asset builders**

Implement methods for BO, BO field, NamingSQL, context, and function registry records. NamingSQL `content` preserves BO, ID, name, description, parameters, and return information. IDs are deterministic, for example `naming_sql:{bo_name}:{naming_sql_id}`. Semantic strings use labeled fields rather than JSON serialization.

- [ ] **Step 4: Implement strict LLM reranking**

Define:

```python
class LLMRerankOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selected_asset_ids: list[str]
    rejected_assets: list[dict] = Field(default_factory=list)
    context_requirement_hints: list[ContextRequirementHint] = Field(default_factory=list)
    evidence_trace: list[ContextEvidenceItem] = Field(default_factory=list)
```

Render candidates with IDs and semantic summaries through the existing `PromptManager`, call the injected existing `LLMClient.complete_json(prompt)`, validate the model, reject duplicate or unknown IDs, and return selected assets in the exact LLM order. Convert transport errors to `LLM_RERANK_FAILED` and contract errors to `INVALID_LLM_OUTPUT`.

- [ ] **Step 5: Add the reranker prompt**

Add `context_namingsql_reranker.zh` to `prompt.json`. It explicitly forbids creating BOs, NamingSQL, context paths, or functions and requires candidate IDs plus evidence in strict JSON.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest tests/test_context_asset_builder.py tests/test_llm_reranker_contract.py -q`

Expected: PASS.

- [ ] **Step 7: Commit resource assets and reranking**

```bash
git add agent/context_manager/resolvers/resource.py agent/context_manager/retrieval/llm_reranker.py prompt.json tests/test_context_asset_builder.py tests/test_llm_reranker_contract.py
git commit -m "feat: rerank semantic resource assets with llm"
```

## Task 4: Resolve Global, EDSL, and Logic-Area Context

**Files:**
- Create: `agent/context_manager/resolvers/global_context.py`
- Create: `agent/context_manager/resolvers/edsl_project.py`
- Create: `agent/context_manager/resolvers/logic_area.py`
- Create: `agent/context_manager/resolvers/__init__.py`
- Test: `tests/test_context_resolvers.py`

- [ ] **Step 1: Write failing resolver tests**

Create a fixture tree containing a parent with local/iter contexts, two siblings, a target fee-table node, and `logic_area_list`. Assert that global rules report both loaded paths, EDSL context identifies parent/ancestors/siblings and fee fields, and explicit node logic-area IDs beat request IDs.

```python
assert block.current_node["node_id"] == "target"
assert block.parent_node["node_id"] == "parent"
assert block.visible_local_context[0]["context_name"] == "$local$.accountId"
assert block.fee_table_summary["group_by_fields"] == ["category"]
assert logic.logic_area_ids == ["la.node"]
assert logic.sa_texts == ["current charge"]
```

- [ ] **Step 2: Run resolver tests and verify failure**

Run: `python -m pytest tests/test_context_resolvers.py -q`

Expected: FAIL because resolver modules do not exist.

- [ ] **Step 3: Implement required rule loading**

`GlobalContextResolver.resolve(request)` reads both required UTF-8 files, rejects missing files with `RULE_FILE_MISSING`, returns non-empty rule records, loaded paths, and evidence.

- [ ] **Step 4: Implement structural EDSL resolution**

Use `jsonpath_ng.parse` to resolve the exact node. Reuse `load_visible_local_context_registry` for visibility and add focused helpers for ancestors and siblings. Support `ab_pivot_table`, `ab_two_level_table`, and `ab_single_mapping_table`. Raise `EDSL_NODE_NOT_FOUND` if the exact path is absent.

- [ ] **Step 5: Implement logic-area resolution**

Read referenced IDs from `current_node`, then request IDs. If neither exists, build logic-area assets and use the injected hybrid retriever plus reranker. Extract SA/SE text recursively from `edsl_semi_struct`, CBS terms, fee requirements, columns, and samples without mutating the tree.

- [ ] **Step 6: Run resolver tests**

Run: `python -m pytest tests/test_context_resolvers.py -q`

Expected: PASS.

- [ ] **Step 7: Commit structural resolvers**

```bash
git add agent/context_manager/resolvers tests/test_context_resolvers.py
git commit -m "feat: resolve project and logic area context"
```

## Task 5: Add OOTB and Site-Knowledge Case Resolvers

**Files:**
- Create: `agent/context_manager/resolvers/reference_cases.py`
- Create: `agent/context_manager/mock_data/ootb_cases.jsonl`
- Create: `agent/context_manager/mock_data/site_knowledge_cases.jsonl`
- Modify: `tests/test_context_resolvers.py`

- [ ] **Step 1: Add failing missing-file and filtered-case tests**

```python
def test_missing_reference_file_is_nonfatal(tmp_path, request, retriever, reranker):
    result = ReferenceCaseResolver(tmp_path / "missing.jsonl", "ootb_case", retriever, reranker).resolve(request, {})
    assert result.candidates == []
    assert result.evidence_trace[0].action == "source_missing"


def test_site_cases_are_filtered_before_recall(site_resolver, request):
    result = site_resolver.resolve(request, {})
    assert {item.case_id for item in result.candidates} == {"site.match"}
```

- [ ] **Step 2: Run the two tests and verify failure**

Run: `python -m pytest tests/test_context_resolvers.py -k 'reference or site_cases' -q`

Expected: FAIL because `ReferenceCaseResolver` does not exist.

- [ ] **Step 3: Implement bounded JSONL loading and retrieval**

Read UTF-8 one object per line, skip malformed lines with evidence, filter site cases by exact `site_id` and either matching or absent `project_id`, build semantic assets, run hybrid recall and reranking, then map only validated IDs to `ReferenceCaseCandidate`.

- [ ] **Step 4: Add valid empty mock corpora**

Create both files as zero-byte valid JSONL corpora. Tests use temporary populated files; production installations can replace them without code changes.

- [ ] **Step 5: Run resolver tests**

Run: `python -m pytest tests/test_context_resolvers.py -q`

Expected: PASS.

- [ ] **Step 6: Commit reference resolvers**

```bash
git add agent/context_manager/resolvers/reference_cases.py agent/context_manager/mock_data tests/test_context_resolvers.py
git commit -m "feat: resolve ootb and site knowledge cases"
```

## Task 6: Assemble and Validate the Final Top-K Context

**Files:**
- Create: `agent/context_manager/renderers/naming_sql_context.py`
- Create: `agent/context_manager/renderers/__init__.py`
- Create: `agent/context_manager/manager/assembler.py`
- Create: `agent/context_manager/manager/context_manager.py`
- Create: `agent/context_manager/manager/__init__.py`
- Create: `agent/context_manager/__init__.py`
- Modify: `prompt.json`
- Test: `tests/test_context_manager_namingsql.py`

- [ ] **Step 1: Write failing end-to-end orchestration tests**

Use capturing fake resolvers and an organizer fake returning two known IDs. Assert exact resolver order, ranks `[1, 2]`, candidate count bounded by `top_k`, hints/constraints retained, and trace concatenated. Add invalid organizer cases for duplicate ID, invented ID, rank gap, and excessive count; each must raise `INVALID_LLM_OUTPUT`.

- [ ] **Step 2: Run manager tests and verify failure**

Run: `python -m pytest tests/test_context_manager_namingsql.py -q`

Expected: FAIL because manager and assembler do not exist.

- [ ] **Step 3: Implement a deterministic prompt renderer**

Serialize bounded request, rule, node, logic-area, resource, OOTB, and site blocks with `json.dumps(..., ensure_ascii=False, sort_keys=True)`. The renderer must omit SQL command bodies and cap long text before rendering.

- [ ] **Step 4: Implement strict organizer assembly**

Define a strict organizer output containing candidate IDs in order, hints, and constraints. Map IDs to canonical candidate models, assign code-owned consecutive ranks, reject duplicate/unknown IDs and output longer than `top_k`, and fail with `NO_NAMING_SQL_CANDIDATES` when no valid candidates remain.

- [ ] **Step 5: Implement fixed-order ContextManager orchestration**

```python
def build_context(self, request: BuildContextRequest) -> NamingSqlSelectionContext:
    if request.chain_type != "namingsql_selection":
        raise ContextBuildError("UNSUPPORTED_CONTEXT_CHAIN", request.chain_type)
    global_block = self.global_resolver.resolve(request)
    node_block = self.edsl_resolver.resolve(request, self.loaded_resource)
    logic_block = self.logic_resolver.resolve(request, self.loaded_resource, node_block)
    resources = self.resource_resolver.resolve(request, self.loaded_resource, node_block, logic_block)
    ootb = self.ootb_resolver.resolve(request, {"node": node_block, "logic": logic_block})
    site = self.site_resolver.resolve(request, {"node": node_block, "logic": logic_block})
    return self.assembler.assemble(request, global_block, node_block, logic_block, resources, ootb, site)
```

- [ ] **Step 6: Add organizer prompt and run tests**

Add `context_namingsql_organizer.zh` to `prompt.json`, requiring strict JSON, no invented resources, and final Top-K ordering. Run: `python -m pytest tests/test_context_manager_namingsql.py tests/test_llm_reranker_contract.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the complete Context Manager**

```bash
git add agent/context_manager prompt.json tests/test_context_manager_namingsql.py
git commit -m "feat: assemble namingsql top k context"
```

## Task 7: Replace the Selector Public API

**Files:**
- Replace: `agent/naming_sql_selector/models.py`
- Replace: `agent/naming_sql_selector/selector.py`
- Replace: `agent/naming_sql_selector/__init__.py`
- Test: `tests/test_namingsql_selector_context_request.py`

- [ ] **Step 1: Write failing facade tests**

```python
def test_selector_constructs_context_request_and_returns_top_k(manager, internal_context):
    manager.result = internal_context
    response = NamingSqlSelector(manager).select(NamingSqlSelectRequest(
        site_id="s", project_id="p", query="fee", node={"node_id": "n"},
        json_path="$.nodes[0]", top_k=2,
    ))
    assert response.success is True
    assert manager.requests[0].top_k == 2
    assert [item.rank for item in response.candidates] == [1, 2]


def test_selector_maps_domain_failure(manager):
    manager.error = ContextBuildError("LLM_ORGANIZER_FAILED")
    response = NamingSqlSelector(manager).select(valid_request())
    assert response.success is False
    assert response.failure_reason == "LLM_ORGANIZER_FAILED"
    assert response.candidates == []
```

- [ ] **Step 2: Run facade tests and verify old-contract failure**

Run: `python -m pytest tests/test_namingsql_selector_context_request.py -q`

Expected: FAIL because the old selector exposes `NamingSqlSelectionRequest` and single-selection results.

- [ ] **Step 3: Replace models and selector**

Implement the approved public request/response models. `NamingSqlSelector.select(request)` creates `BuildContextRequest`, calls `build_context`, maps final candidates/hints/constraints/trace, includes `prompt_view` only for debug requests, and catches only `ContextBuildError` to produce stable failure responses.

- [ ] **Step 4: Run facade tests**

Run: `python -m pytest tests/test_namingsql_selector_context_request.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the breaking selector replacement**

```bash
git add agent/naming_sql_selector tests/test_namingsql_selector_context_request.py
git commit -m "feat: replace namingsql selector with top k facade"
```

## Task 8: Migrate ValueLogicGenerator, Environment, and Planner

**Files:**
- Modify: `agent/environment/environment.py`
- Modify: `agent/value_logic_generator.py`
- Modify: `agent/planner/llm_planner.py`
- Replace: `agent/naming_sql_selector/plan_validator.py`
- Modify: `tests/test_value_logic_generator.py`
- Modify: `tests/test_llm_planner.py`
- Modify: `tests/test_naming_sql_plan_validator.py`

- [ ] **Step 1: Replace old integration fixtures with Top-K fixtures**

Use a response containing two candidates and a capturing `selector_factory(loaded_resource)`. Add assertions that non-NamingSQL routes do not call the factory, NamingSQL routes pass the current request's `LoadedResource` into it, successful routes store the response for planner use, failure stops before planner, planner prompt contains both Top-K summaries but not sibling SQL from BO registries, and validator rejects `fetch.name` outside the Top-K.

```python
assert resources["naming_sql_candidates"][0]["rank"] == 1
assert {item["name"] for item in resources["naming_sql_candidates"]} == {"FindCustomer", "FindCustomerByAccount"}
assert "SiblingSql" not in client.calls[0]["prompt"]
```

- [ ] **Step 2: Run integration tests and observe old-type failures**

Run: `python -m pytest tests/test_value_logic_generator.py tests/test_llm_planner.py tests/test_naming_sql_plan_validator.py -q`

Expected: FAIL where code imports `NamingSqlSelectionResult` or assumes `.selected`.

- [ ] **Step 3: Migrate environment and generator**

Change `FilteredEnvironment.naming_sql_selection` to `NamingSqlSelectResponse | None`. Replace the long-lived `naming_sql_selector` constructor dependency with `naming_sql_selector_factory: Callable[[LoadedResource], NamingSqlSelector]`. The default factory builds request-scoped resolvers, `ContextManager(loaded_resource=loaded)`, and `NamingSqlSelector(manager)`. On the NamingSQL route, call the factory with `ctx.resources.loaded`, construct the new request with `project_id`, `json_path=request.node_path`, BO hint, and default Top-K, then call `select(request)`. Raise `ValueError(response.failure_reason)` when `success=False` and do not call the planner. This keeps registry access inside Context Manager while ensuring the EDSL tree belongs to the current generation request.

- [ ] **Step 4: Expose bounded Top-K to planner**

Replace the single-selection summary with:

```python
summary["naming_sql_candidates"] = [
    {
        "bo": item.bo_name,
        "id": item.naming_sql_id,
        "name": item.naming_sql_name,
        "rank": item.rank,
        "params": [p.get("param_name") for p in item.param_list],
        "return_type": item.return_type,
        "evidence": item.evidence[:3],
    }
    for item in selection.candidates
]
summary["naming_sql_context_requirements"] = [item.model_dump(mode="json") for item in selection.context_requirements_hint]
summary["naming_sql_constraints"] = selection.selection_constraints.model_dump(mode="json")
```

Never include the BO registry's full NamingSQL list when a Top-K response is present.

- [ ] **Step 5: Replace fixed-selection validation**

Collect allowed names and each candidate's parameter-name set. For each fetch plan node, reject unknown SQL with `NAMING_SQL_OUTSIDE_TOP_K` and reject unknown argument names with `NAMING_SQL_UNKNOWN_PARAM`. Permit the planner to choose any one of the Top-K.

- [ ] **Step 6: Run integration and ordinary-path tests**

Run: `python -m pytest tests/test_value_logic_generator.py tests/test_llm_planner.py tests/test_naming_sql_plan_validator.py tests/test_expression_generator.py -q`

Expected: PASS.

- [ ] **Step 7: Commit caller migration**

```bash
git add agent/environment/environment.py agent/value_logic_generator.py agent/planner/llm_planner.py agent/naming_sql_selector/plan_validator.py tests/test_value_logic_generator.py tests/test_llm_planner.py tests/test_naming_sql_plan_validator.py
git commit -m "feat: route namingsql top k into planner"
```

## Task 9: Remove Legacy Profiles, Complete Exports, and Verify

**Files:**
- Modify: `agent/resource_manager/loader/resource_loader.py`
- Delete: `agent/naming_sql_selector/knowledge.py`
- Delete: `agent/naming_sql_selector/profile_builder.py`
- Delete: `agent/naming_sql_selector/spec_generator.py`
- Replace: `tests/test_naming_sql_selector.py`
- Delete or replace: `tests/test_naming_sql_profile_builder.py`
- Modify: `README.md`

- [ ] **Step 1: Add a failing resource-loader regression test**

Assert that `LoadedResource` has BO, context, function, EDSL, and domain registries but no `naming_sql_profiles`, while raw `BoRegistry.naming_sql_list` remains intact for Context Manager adaptation.

- [ ] **Step 2: Run the regression test and verify old cache presence**

Run: `python -m pytest tests/test_resource_loader.py -q`

Expected: FAIL because `LoadedResource` still exposes `naming_sql_profiles`.

- [ ] **Step 3: Remove profile-cache coupling and legacy modules**

Remove `NamingSqlProfile`/`NamingSqlProfileBuilder` imports, the profile field, fingerprint helper, and profile cache from `resource_loader.py`. Delete the three legacy selector modules after `rg` confirms no runtime imports remain. Replace old selector/profile tests with assertions covered by the new Context Manager suites.

- [ ] **Step 4: Document configuration and route behavior**

Add a concise README section listing the four required OpenAI variables, Top-K route behavior, explicit failure when AI services are unavailable, and the rule/mock-data locations.

- [ ] **Step 5: Run static repository scans**

Run:

```bash
rg "NamingSqlSelectionResult|NamingSqlSelectionRequest|NamingSqlProfileBuilder|deterministic relevance score" agent tests
rg "OPENAI_EMBEDDING_MODEL|NamingSqlSelectResponse|ContextManager" agent README.md
```

Expected: first command returns no matches; second returns the new configuration and contracts.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`

Expected: all tests PASS with no network access.

- [ ] **Step 7: Check formatting and repository state**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` emits nothing; status lists only the intended Task 9 files.

- [ ] **Step 8: Commit cleanup and documentation**

```bash
git add -A agent/naming_sql_selector agent/resource_manager/loader/resource_loader.py tests/test_naming_sql_selector.py tests/test_naming_sql_profile_builder.py tests/test_resource_loader.py README.md
git commit -m "refactor: remove legacy namingsql ranking pipeline"
```

- [ ] **Step 9: Record final verification evidence**

Run: `python -m pytest -q && git status --short`

Expected: all tests PASS and the worktree is clean.
