# NamingSQL Context Manager Replacement Design

## Status

Approved in design discussion on 2026-07-02. This document defines the replacement architecture and contracts. It does not authorize implementation changes.

## Problem

The repository currently has a `NamingSqlSelector` that performs deterministic BO and NamingSQL ranking, parameter binding, and final single-SQL selection. The replacement must instead build rich task context from project and resource facts, use embeddings for semantic recall, and use LLMs for reranking and final Top-K organization.

`ValueLogicGenerator` must call the selector only when the request requires NamingSQL. The selector returns the final ordered Top-K NamingSQL candidates, and the generator passes that result to the planner. The planner may plan data access and parameter bindings from those candidates, but it may not use NamingSQL definitions outside the Top-K.

This is a breaking replacement. Existing selector request/result contracts and their callers will be migrated rather than supported through a compatibility layer.

## Goals

- Introduce a minimal, extensible Context Manager for the `namingsql_selection` chain.
- Keep resource loading, retrieval, reranking, and context organization outside `NamingSqlSelector`.
- Reuse `LoadedResource` and existing registries as the authoritative resource and EDSL project source.
- Normalize all searchable inputs as typed `ContextAsset` instances with semantic `index_text`.
- Use embeddings for semantic recall and lexical matching for exact-match supplementation.
- Use an LLM reranker and LLM organizer for final candidate selection and ordering.
- Return an ordered Top-K NamingSQL result with evidence, context requirements, and constraints.
- Preserve clear extension points for other context-building chains.
- Keep all external AI clients replaceable with fakes in tests.

## Non-Goals

- Generating a final expression inside the Context Manager or selector.
- Producing final parameter bindings inside the Context Manager or selector.
- Allowing the selector to read BO, NamingSQL, context, function, EDSL, OOTB, or site-knowledge data directly.
- Adding an external vector database in the first version.
- Supporting the old selector contracts after migration.
- Refactoring the ordinary non-NamingSQL expression-generation path.

## Architecture

The replacement is a single-direction pipeline:

```text
ValueLogicGenerator
  -> determine whether NamingSQL is required
  -> NamingSqlSelector.select
  -> BuildContextRequest
  -> ContextManager.build_context
  -> resolvers collect context, candidates, and evidence
  -> embedding and lexical recall
  -> LLM rerank
  -> LLM organizer produces final Top-K
  -> NamingSqlSelector returns Top-K response
  -> ValueLogicGenerator passes response to Planner
```

### Package layout

New Context Manager code lives under the existing `agent` package:

```text
agent/context_manager/
  models/
  manager/
  resolvers/
  retrieval/
  llm/
  renderers/
  mock_data/

agent/naming_sql_selector/
  __init__.py
  models.py
  selector.py
```

The selector package is destructively simplified. Its old deterministic ranker, final single-SQL selection, parameter-binding planner, profile ranking, reviewer contracts, and selection-specific plan validator are removed or replaced by the new contracts.

### Responsibility boundaries

- `ResourceLoader` and `LoadedResource` remain the authoritative source for BOs, NamingSQL definitions, contexts, functions, and the current EDSL tree.
- Context resolvers receive `LoadedResource` through dependency injection. They adapt registry entities into `ContextAsset`; they do not create a second persisted resource model.
- `json_path` is an EDSL node path inside `LoadedResource.edsl_tree`, not a filesystem path.
- `ContextManager` loads and retrieves context, calls embedding and LLM services, validates their outputs, and produces the final ordered Top-K.
- `NamingSqlSelector` constructs a context request, calls `ContextManager`, and maps success or failure to its public response. It performs no retrieval or ranking.
- `ValueLogicGenerator` owns the decision to invoke the NamingSQL route.
- `Planner` consumes only the returned Top-K plus requirements and constraints. It may perform downstream expression planning and parameter binding, but it may not introduce an out-of-set NamingSQL.

## Public Contracts

### NamingSqlSelectRequest

```python
class NamingSqlSelectRequest(BaseModel):
    site_id: str
    project_id: str
    query: str
    node: dict
    json_path: str

    target_bo_name: str | None = None
    parent_bo_hint: str | None = None
    target_logic_area_id_list: list[str] = Field(default_factory=list)

    top_k: int = Field(default=5, ge=1, le=20)
    debug: bool = False
```

### NamingSqlSelectResponse

```python
class NamingSqlSelectResponse(BaseModel):
    success: bool
    candidates: list[NamingSqlCandidate] = Field(default_factory=list)
    context_requirements_hint: list[ContextRequirementHint] = Field(default_factory=list)
    selection_constraints: NamingSqlSelectionConstraints | None = None
    evidence_trace: list[ContextEvidenceItem] = Field(default_factory=list)
    prompt_view: dict | None = None
    failure_reason: str | None = None
```

`prompt_view` is populated only when `debug=True`. Evidence is compact in normal mode and includes full stage diagnostics in debug mode.

### NamingSqlCandidate

```python
class NamingSqlCandidate(BaseModel):
    candidate_id: str
    bo_name: str
    naming_sql_id: str
    naming_sql_name: str | None = None
    annotation: str = ""
    param_list: list[dict] = Field(default_factory=list)
    return_type: dict | None = None
    source: CandidateSource
    rank: int
    evidence: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    retrieval_metadata: dict = Field(default_factory=dict)
```

`rank` is the validated LLM organizer order. It is not derived from a code-side weighted score. `retrieval_metadata` may retain embedding similarity and lexical hit information for diagnostics, but code must not combine these values into the final order.

## Internal Contracts

### BuildContextRequest

The internal request contains the public request fields plus:

```python
chain_type: Literal[
    "namingsql_selection",
    "expression_generation",
    "node_generation",
    "node_modification",
    "context_selection",
] = "namingsql_selection"
max_context_items: int = 50
top_k: int = 5
```

Only `namingsql_selection` is implemented in this change. Other chain values are model-level extension points and must fail with an explicit unsupported-chain error until implemented.

### ContextAsset

Every resolver normalizes searchable data into a typed asset containing:

- stable `asset_id` and `asset_type`;
- scope and optional site, project, logic-area, and node identifiers;
- structured `content`;
- asset-specific semantic `index_text`;
- source, version, and metadata.

Raw serialized JSON is not an acceptable sole `index_text`. Builders must express the semantics appropriate to each asset type. A NamingSQL asset, for example, includes its BO, purpose, parameters, return type, field summary, and suitable scenarios.

### NamingSqlSelectionContext

`ContextManager.build_context` returns an internal structured context containing:

- request summary;
- global rules and loaded indexes;
- current node and structural EDSL context;
- optional logic-area and project-search context;
- final resource candidates, whose NamingSQL list is already the ordered Top-K;
- OOTB and site-knowledge references retained by the organizer;
- context requirement hints;
- selection constraints;
- evidence trace;
- optional debug prompt view.

The selector maps this internal object to `NamingSqlSelectResponse`; callers do not receive the full internal context model.

## Resolver Pipeline

`ContextManager` executes resolvers in a fixed order.

### 1. GlobalContextResolver

It reads:

```text
agent_rules/GLOBAL.md
agent_rules/chains/namingsql_selection.md
```

Both files are required for this chain. The resolver returns parsed rule summaries, loaded paths, and evidence. Other chain files may exist as future extension points but are not loaded for this request.

### 2. EdslProjectContextResolver

It locates `json_path` in the injected EDSL tree and extracts:

- current, parent, ancestor, and sibling summaries;
- visible local and iterator context;
- existing data source, BO name, and NamingSQL IDs;
- simple-leaf fields such as XML name, annotation, semi-structured data, data type, expression, and logic-area references;
- fee-table fields for pivot, two-level, and single-mapping table nodes.

Failure to locate `json_path` is fatal. The resolver does not silently substitute the request's `node` for project truth.

### 3. LogicAreaContextResolver

Lookup priority is:

1. `node.reference_logic_area_id_list`;
2. `request.target_logic_area_id_list`;
3. semantic retrieval using query, node name, and annotation.

The resolver extracts logic-area identity and description, SA/SE text, CBS terms, fee-category summaries, columns, and samples.

### 4. ResourceContextResolver

It adapts existing BO, BO field, NamingSQL, global context, and function registries into `ContextAsset` values. It then:

1. performs embedding Top-N recall;
2. supplements candidates with lexical exact matches for names, fields, parameters, and explicit hints;
3. deduplicates the candidate union without imposing a final relevance order;
4. passes the bounded union to the LLM reranker;
5. maps selected asset IDs back to typed candidates and records evidence.

### 5. OOTBContextResolver

The first version reads `agent/context_manager/mock_data/ootb_cases.jsonl`. It builds semantic text from case descriptions, node patterns, logic-area terms, and referenced data access, then uses embedding recall and LLM reranking.

### 6. SiteKnowledgeContextResolver

The first version reads `agent/context_manager/mock_data/site_knowledge_cases.jsonl`, filters by `site_id` and compatible `project_id`, and uses embedding recall plus LLM reranking. It preserves historical and manually corrected case evidence.

### 7. ContextPackAssembler

The assembler merges resolver outputs, enforces the context-item budget, renders the organizer prompt, invokes the LLM organizer, and validates the result. The organizer must:

- select and order at most `top_k` NamingSQL candidates;
- generate context requirement hints and selection constraints;
- retain task-relevant evidence;
- use only supplied candidate IDs and facts;
- return strict JSON.

The assembler supplements immutable request fields and canonical resource entities in code after validation. The LLM does not rewrite source facts.

## Retrieval and LLM Rules

- Embeddings and lexical matching are recall mechanisms only.
- No code-side weighted total may define the final candidate order.
- The LLM reranker may select only IDs supplied in its candidate payload.
- The organizer may output only NamingSQL candidates retained by the reranker.
- Unknown, duplicate, or malformed IDs invalidate the LLM stage; they are never silently accepted.
- Final ranks are consecutive integers beginning at one.
- The final candidate count is `min(top_k, valid_available_candidates)`.
- Every resolver appends evidence describing source, action, optional asset ID, rationale, and structured payload.

LLM prompts emphasize that the model is selecting context and Top-K NamingSQL candidates, not generating expressions, resources, context paths, or parameter bindings.

## AI Client Boundaries

The feature introduces replaceable client protocols with production OpenAI-compatible implementations:

```python
class LLMClient:
    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel] | None = None,
    ) -> dict: ...

class EmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
```

Production configuration uses `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_EMBEDDING_MODEL`. Business logic depends on the protocols, not the OpenAI SDK. Unit tests inject deterministic fakes.

## Failure Semantics

The production route requires both embeddings and LLMs. It does not fall back to deterministic final ranking.

- Missing or unusable AI configuration: `success=False`.
- Embedding, reranker, or organizer call failure: `success=False`.
- Invalid JSON or schema: `success=False`.
- Unknown IDs, duplicates, non-consecutive ranks, or excessive candidate count: `success=False`.
- No valid NamingSQL candidate: `success=False` with `NO_NAMING_SQL_CANDIDATES`.
- Missing global or chain rule file: `success=False`.
- Missing EDSL node path: `success=False`.
- Missing OOTB or site-knowledge mock file: non-fatal empty enhancement source with trace evidence.
- Malformed individual resource: skip it and record evidence; continue if valid candidates remain.

The selector maps expected domain errors to stable failure codes. Responses must not expose secrets, raw credentials, or sensitive prompt internals.

## ValueLogicGenerator and Planner Integration

`ValueLogicGenerator` retains the existing NamingSQL-routing decision. If NamingSQL is not required, the ordinary generation path is unchanged. If it is required:

1. construct the new request, including project identity, node path, and desired `top_k`;
2. call `NamingSqlSelector`;
3. stop the NamingSQL route on failure;
4. store the successful Top-K response in the filtered environment;
5. pass only those candidates, requirements, constraints, and evidence to the planner.

The planner prompt no longer receives the selected BO's full NamingSQL list. Validation ensures that a generated plan references a NamingSQL present in the Top-K and uses only parameter names defined by that candidate. A planner cannot bypass selector failure or introduce a full-list fallback.

The old `NamingSqlSelectionResult`, fixed single selection, deterministic scores, and binding-plan assumptions are removed from `FilteredEnvironment`, planner typing, and tests.

## Testing Strategy

All automated tests use fake LLM and embedding clients and require no network access.

### Contract tests

- Selector maps all public fields, including `top_k`, into `BuildContextRequest`.
- `top_k` accepts 1 through 20 and rejects values outside that range.
- Selector maps internal success and stable domain failures to the public response.

### Asset tests

- BO, NamingSQL, context, and function builders produce asset-specific semantic text.
- `index_text` is not a raw JSON dump.
- Stable IDs map back to authoritative registry entities.

### Resolver tests

- EDSL resolver extracts node relationships, local/iterator context, and fee-table summaries.
- Logic-area resolver respects lookup priority and extracts SA/SE, CBS, and fee-category data.
- Resource, OOTB, and site resolvers union semantic and lexical recall before LLM reranking.
- All resolvers emit evidence.

### LLM contract tests

- Reranker accepts only supplied asset IDs and strict JSON.
- Organizer returns no more than `top_k`, consecutive ranks, no duplicates, and only retained NamingSQL IDs.
- Invented or malformed identifiers fail the stage.
- Retrieval metadata cannot change organizer order in code.

### Integration tests

- Context Manager executes resolvers in the required order and returns Top-K candidates, hints, constraints, and trace.
- `ValueLogicGenerator` invokes the selector only for NamingSQL requests.
- A successful result reaches the planner without exposing the full NamingSQL list.
- Planner validation rejects out-of-Top-K SQL and unknown parameter names.
- AI service failure stops the NamingSQL route.
- Ordinary non-NamingSQL generation remains unchanged.

Existing tests for the old public contracts are replaced with new-contract tests rather than preserved as compatibility assertions.

## Completion Criteria

The replacement is complete when:

1. `ValueLogicGenerator` calls the selector only for NamingSQL requests.
2. The selector returns a validated ordered Top-K result rather than an internal context or single selected SQL.
3. Context Manager loads global, EDSL, logic-area, resource, OOTB, and site context through separated resolvers.
4. Embeddings perform semantic recall and LLMs perform reranking and final organization.
5. No deterministic weighted total determines final ordering.
6. Every returned candidate maps to an authoritative loaded resource and carries evidence.
7. Planner input contains only the Top-K and cannot reference candidates outside it.
8. Missing required AI capability produces explicit failure.
9. Fake clients make unit and integration tests deterministic.
10. The ordinary expression-generation path and AST rendering remain unaffected.
