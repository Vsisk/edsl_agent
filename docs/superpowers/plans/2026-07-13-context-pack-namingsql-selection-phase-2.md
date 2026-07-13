# ContextPack-Driven NamingSQL Selection Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NamingSQL selection consume a previously built `ContextPack`, apply canonical deterministic recall plus optional LLM selection, and migrate `ValueLogicGenerator` away from the dedicated NamingSQL Context Manager orchestration.

**Architecture:** `ContextPackManager` remains an independent context-recall layer for `current_tree`, `dev_skill`, and `ootb_edsl`. A new bounded adapter turns its output into NamingSQL selection signals; a request-scoped selector uses only those signals and the authoritative `LoadedResource`, falls back deterministically when AI stages fail, and preserves the existing planner/validator boundary.

**Tech Stack:** Python 3.12, Pydantic 2, pytest, existing `ContextPack`, `LoadedResource`, `ResourceAssetBuilder`, `HybridRetriever`, `LLMReranker`, and NamingSQL planner validation.

---

## Scope and file map

- Create `agent/naming_sql_selector/context_adapter.py`: bounded conversion from `ContextPack` to selection signals.
- Create `agent/naming_sql_selector/retrieval.py`: canonical candidate construction, hard filtering, deterministic ordering, and optional AI refinement.
- Modify `agent/naming_sql_selector/models.py`: pack-bearing request and explicit selection-mode/warning response contract.
- Modify `agent/naming_sql_selector/selector.py`: direct two-layer orchestration without `ContextManager.build_context`.
- Modify `agent/naming_sql_selector/__init__.py`: expose new public contracts.
- Modify `agent/value_logic_generator.py`: build ContextPack before NamingSQL selection and inject request-scoped dependencies.
- Modify `agent/context_pack/models/request.py` and documentation: remove NamingSQL from the public resource whitelist.
- Modify `agent/context_pack/README.md`, `agent/context_manager/README.md`, and root `README.md`: document the new boundary and compatibility status.
- Add focused tests under `tests/test_namingsql_*`, `tests/test_context_pack_models.py`, and `tests/test_value_logic_generator.py`.

## Task 1: Close the ContextPack resource boundary

**Files:**
- Modify: `agent/context_pack/models/request.py`
- Modify: `agent/context_pack/README.md`
- Test: `tests/test_context_pack_models.py`
- Test: `tests/test_context_pack_registry_manager.py`

- [ ] Add a failing contract test asserting `ContextPackRequest(..., resource_names=["namingsql"])` raises validation error while the three recall resources remain valid.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_context_pack_models.py tests/test_context_pack_registry_manager.py -q`; expect the new test to fail because `ResourceName.NAMING_SQL` is still accepted.
- [ ] Remove `NAMING_SQL` from `ResourceName`, remove its stable-order entry, and update tests that previously expected a registered-name/missing-provider error.
- [ ] Update the Phase 1 README to state that NamingSQL is a downstream decision consuming ContextPack, not a ContextPack resource.
- [ ] Run the focused tests; expect all pass.
- [ ] Commit with `git add agent/context_pack/models/request.py agent/context_pack/README.md tests/test_context_pack_models.py tests/test_context_pack_registry_manager.py && git commit -m "refactor: separate namingsql from context resources"`.

## Task 2: Define ContextPack-aware selection contracts

**Files:**
- Modify: `agent/naming_sql_selector/models.py`
- Test: `tests/test_namingsql_selector_context_request.py`

- [ ] Write failing tests requiring `context_pack: ContextPack` on `NamingSqlSelectRequest`; add strict enum `SelectionMode(llm, deterministic_fallback)`, response `selection_mode`, and `warnings: list[str]`. Assert successful responses require a mode, failed responses forbid a mode, and defaults are independent.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_namingsql_selector_context_request.py -q`; expect missing fields/types.
- [ ] Add `context_pack` to the strict request; define `SelectionMode`; extend the response validator so success requires candidates and a mode while failure requires a stable reason and has no mode/candidates/prompt view.
- [ ] Preserve strict deep-copy validation of candidates, hints, constraints, and evidence.
- [ ] Run the focused test; expect all pass.
- [ ] Commit with `git add agent/naming_sql_selector/models.py tests/test_namingsql_selector_context_request.py && git commit -m "feat: add context pack selection contracts"`.

## Task 3: Adapt ContextPack into bounded selection signals

**Files:**
- Create: `agent/naming_sql_selector/context_adapter.py`
- Modify: `agent/naming_sql_selector/__init__.py`
- Test: `tests/test_namingsql_context_adapter.py`

- [ ] Write failing tests for complete, partial, and failed packs. Assert stable section order, bounded summaries, current-tree facts, skill rules, OOTB references, conflicts, pack warnings, and trim trace are represented without mutating the pack.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_namingsql_context_adapter.py -q`; expect missing adapter imports.
- [ ] Define strict `NamingSqlSelectionContext` with `query_terms`, `authoritative_facts`, `normative_rules`, `reference_examples`, and `warnings`. Implement `NamingSqlContextAdapter(max_items_per_section=10, max_chars=12000)`.
- [ ] Reject `PackStatus.FAILED` with stable `CONTEXT_PACK_FAILED`; accept partial packs and append stable section-status warnings. Serialize only item summaries, structured facts, IDs, and locator identities—never arbitrary source files or full project trees.
- [ ] Run the focused tests; expect all pass.
- [ ] Commit with `git add agent/naming_sql_selector/context_adapter.py agent/naming_sql_selector/__init__.py tests/test_namingsql_context_adapter.py && git commit -m "feat: adapt context packs for namingsql selection"`.

## Task 4: Build canonical deterministic NamingSQL retrieval

**Files:**
- Create: `agent/naming_sql_selector/retrieval.py`
- Test: `tests/test_namingsql_context_retrieval.py`

- [ ] Write failing tests with multiple BOs and NamingSQL definitions. Cover exact BO/ID/name hits, BO hints, parameter/field overlap from adapted context, stable ties, Top-K bounds, zero candidates, canonical object reconstruction, and input immutability.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_namingsql_context_retrieval.py -q`; expect missing retriever.
- [ ] Implement `NamingSqlCandidateRetriever` using `ResourceAssetBuilder.naming_sql` to construct assets only from `LoadedResource.bo_registry`. Apply explicit ID/BO hard constraints before scoring.
- [ ] Combine pinned exact hits, lexical/context token overlap, and injectable `HybridRetriever` output into a deterministic union. Canonicalize every returned asset against the registry-built asset map and convert through the existing candidate shape.
- [ ] Return a bounded pre-LLM candidate list plus evidence; raise stable `NO_NAMING_SQL_CANDIDATES` only when no canonical survivor exists.
- [ ] Run the focused tests; expect all pass.
- [ ] Commit with `git add agent/naming_sql_selector/retrieval.py tests/test_namingsql_context_retrieval.py && git commit -m "feat: retrieve namingsql from context pack signals"`.

## Task 5: Add optional LLM refinement with deterministic fallback

**Files:**
- Modify: `agent/naming_sql_selector/retrieval.py`
- Modify: `agent/naming_sql_selector/selector.py`
- Test: `tests/test_namingsql_llm_selection.py`

- [ ] Write failing tests for valid LLM ordering and for configuration, transport, invalid schema, unknown ID, duplicate ID, excess count, and empty output failures. Every failure must return the deterministic Top-K with `selection_mode=deterministic_fallback`, a stable warning, and evidence.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_namingsql_llm_selection.py -q`; expect selector/retrieval contract failures.
- [ ] Refactor `NamingSqlSelector` to accept `loaded_resource`, `context_adapter`, `candidate_retriever`, and optional `reranker`. Remove conversion to `BuildContextRequest` and all calls to `manager.build_context`.
- [ ] Pass opaque asset IDs, canonical summaries, and the bounded selection context to the existing reranker. Accept only unique IDs from the supplied candidate set, cap at requested Top-K, then remap to canonical candidates.
- [ ] Catch only documented AI/configuration/contract errors for fallback; preserve unexpected programmer exceptions. Sanitize warnings to stable codes and do not expose private exception text.
- [ ] Run the focused tests; expect all pass.
- [ ] Commit with `git add agent/naming_sql_selector/retrieval.py agent/naming_sql_selector/selector.py tests/test_namingsql_llm_selection.py && git commit -m "feat: refine namingsql selection with optional llm"`.

## Task 6: Migrate ValueLogicGenerator to the two-layer flow

**Files:**
- Modify: `agent/value_logic_generator.py`
- Modify: `tests/test_value_logic_generator.py`
- Test: `tests/test_namingsql_selector_integration.py`

- [ ] Add failing tests asserting NamingSQL routes call `ContextPackManager.build` before selector selection, pass the exact resulting pack, use request-scoped `LoadedResource`, and forward only approved candidates to typed context/planner. Assert non-NamingSQL routes do not call the selector.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_value_logic_generator.py tests/test_namingsql_selector_integration.py -q`; expect missing ContextPack dependencies and request field.
- [ ] Add injectable `context_pack_manager` and project-context factory. Build a request using `current_tree` plus configured `dev_skill`/`ootb_edsl` resources; construct `ProjectContext` from the current request tree, configured OOTB tree/skill path, and loaded resources.
- [ ] Change `naming_sql_selector_factory` to build the new request-scoped selector from `LoadedResource`; pass `context_pack` into `NamingSqlSelectRequest`.
- [ ] Keep typed-context construction, planner prompt narrowing, `validate_naming_sql_plan`, AST validation, and non-NamingSQL behavior unchanged.
- [ ] Run the focused and existing planner/typed-context suites; expect all pass.
- [ ] Commit with `git add agent/value_logic_generator.py tests/test_value_logic_generator.py tests/test_namingsql_selector_integration.py && git commit -m "feat: drive namingsql selection from context packs"`.

## Task 7: Remove obsolete orchestration dependencies and update docs

**Files:**
- Modify: `agent/context_manager/README.md`
- Modify: `agent/naming_sql_selector/README.md` if present, otherwise create it
- Modify: `README.md`
- Modify: imports/tests that instantiate `NamingSqlSelector(ContextManager(...))`

- [ ] Search with `rg -n "NamingSqlSelector\(ContextManager|build_context\(|ResourceName\.NAMING_SQL|\"namingsql\"" agent tests README.md` and classify every hit as retained low-level compatibility or obsolete orchestration.
- [ ] Update all supported construction examples and tests to the pack-aware factory. Remove production imports of `ContextManager` from `ValueLogicGenerator` and `NamingSqlSelector`.
- [ ] Document the two-layer flow, deterministic fallback, canonical guarantees, selection modes, stable failure/warning codes, and planner boundary.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_context_pack_models.py tests/test_namingsql_selector_context_request.py tests/test_namingsql_context_adapter.py tests/test_namingsql_context_retrieval.py tests/test_namingsql_llm_selection.py tests/test_namingsql_selector_integration.py tests/test_value_logic_generator.py tests/test_llm_planner.py tests/test_naming_sql_plan_validator.py tests/test_typed_expression_context.py -q`; expect all pass.
- [ ] Commit with `git add agent README.md tests && git commit -m "docs: complete context pack namingsql migration"`.

## Task 8: Final verification and handoff

- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_context_pack_models.py tests/test_context_pack_registry_manager.py tests/test_context_pack_search.py tests/test_context_pack_markdown_skill.py tests/test_context_pack_edsl_index.py tests/test_context_pack_current_tree.py tests/test_context_pack_ootb.py tests/test_context_pack_builder.py tests/test_context_pack_integration.py -q`.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_namingsql_selector_context_request.py tests/test_namingsql_context_adapter.py tests/test_namingsql_context_retrieval.py tests/test_namingsql_llm_selection.py tests/test_namingsql_selector_integration.py tests/test_value_logic_generator.py tests/test_llm_planner.py tests/test_naming_sql_plan_validator.py tests/test_typed_expression_context.py -q`.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q`; expect all tests pass except explicit skips.
- [ ] Run `rg -n "ResourceName\.NAMING_SQL|NamingSqlSelector\(ContextManager|T[B]D|T[O]DO" agent tests README.md docs/superpowers/specs/2026-07-13-context-pack-namingsql-selection-design.md` and verify no stale production boundary or placeholders remain.
- [ ] Run `git diff --check`, `git status --short`, and inspect every remaining diff.
- [ ] Handoff public factory signatures, ContextPack resource list, selection request/response contract, fallback warning codes, retained low-level `agent.context_manager` components, and exact verification commands.
