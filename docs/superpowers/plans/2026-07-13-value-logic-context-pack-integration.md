# ValueLogicGenerator ContextPack Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one routed ContextPack before spec generation and pass the same pack through every downstream ValueLogic stage.

**Architecture:** A small fail-open Boolean LLM router controls only `current_tree`; `dev_skill` and `ootb_edsl` are always requested. `ValueLogicGenerator` builds one ContextPack, stores it in `GenerationContext`, and passes it explicitly to spec generation, NamingSQL selection, typed-context construction, and planning through a shared bounded prompt renderer.

**Tech Stack:** Python, Pydantic, pytest, existing `LLMClient`, `generate_by_llm`, `ContextPackManager`, and prompt templates.

---

### Task 1: Implement the lightweight context resource router

**Files:**
- Create: `agent/context_pack/resource_router.py`
- Modify: `agent/context_pack/__init__.py`
- Modify: `prompt.json`
- Test: `tests/test_context_pack_resource_router.py`

- [ ] Write failing tests for strict `true/false`, unavailable client, exceptions, non-object response, missing field, and non-Boolean values.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_context_pack_resource_router.py -q`; expect missing imports.
- [ ] Implement frozen `ContextResourceRoute` and `FastContextResourceRouter`; accept only a strict Boolean and return `use_current_tree=True, fallback=True` for every failure without retry.
- [ ] Add a short `context_resource_router` prompt receiving bounded query/current/parent summaries and requiring only `{"use_current_tree": true}`.
- [ ] Run focused tests and commit `feat: route context pack resources`.

### Task 2: Add a bounded shared ContextPack prompt renderer

**Files:**
- Create: `agent/context_pack/prompt_renderer.py`
- Modify: `agent/context_pack/__init__.py`
- Test: `tests/test_context_pack_prompt_renderer.py`

- [ ] Write failing tests for stable JSON, section/item/fact projection, warnings/conflicts, item and character bounds, and exclusion of full content/SQL/private warning text.
- [ ] Run the test and confirm missing renderer.
- [ ] Implement `ContextPackPromptRenderer(max_items=30, max_chars=20000)` and `render_json(pack)`.
- [ ] Run focused tests and commit `feat: render bounded context packs`.

### Task 3: Build one ContextPack at ValueLogic entry

**Files:**
- Modify: `agent/value_logic_generator.py`
- Modify: `tests/test_value_logic_generator.py`

- [ ] Add failing call-order tests showing route and pack build happen before spec generation, fixed resources are always present, `current_tree` follows the route, fallback uses all three resources, and non-NamingSQL requests still build exactly once.
- [ ] Run focused tests and confirm the existing late NamingSQL-only build fails them.
- [ ] Add `GenerationContext.context_pack`; inject `context_resource_router`, `dev_skill_path`, and `ootb_tree`; build the pack once in `generate()` and remove the NamingSQL-branch build.
- [ ] Append stable fallback warning/trace through a deep model copy, without mutating provider output.
- [ ] Run focused tests and commit `feat: build context pack before value logic`.

### Task 4: Pass ContextPack to spec and typed-context stages

**Files:**
- Modify: `agent/value_logic_generator.py`
- Modify: `agent/expression_generation/typed_context.py`
- Modify: `tests/test_value_logic_generator.py`
- Modify: `tests/test_typed_expression_context.py`

- [ ] Add failing tests that the exact pack object reaches `ExpressionSpecGenerator.generate` and `TypedExpressionContextBuildInput.context_pack`.
- [ ] Run focused tests and confirm missing keyword/field failures.
- [ ] Extend both contracts and update all injected test implementations to accept the explicit keyword.
- [ ] Preserve existing typed registry authority; the new field is contextual input and does not override canonical types.
- [ ] Run focused tests and commit `feat: share context pack with specification stages`.

### Task 5: Pass bounded ContextPack to both planners

**Files:**
- Modify: `agent/planner/llm_planner.py`
- Modify: `agent/planner/simple_expression_planner.py`
- Modify: `prompt.json`
- Modify: `tests/test_llm_planner.py`
- Modify: `tests/test_simple_expression_planner.py`
- Modify: `tests/test_value_logic_generator.py`

- [ ] Add failing tests that both planners receive the exact pack and render the bounded `context_pack_json` into normal and repair prompts.
- [ ] Run focused tests and confirm missing signature/template variables.
- [ ] Add optional `context_pack` parameters, use the shared renderer, pass JSON to both prompt templates, and make `ValueLogicGenerator` supply `ctx.context_pack`.
- [ ] Run planner and generator suites; commit `feat: provide context packs to planners`.

### Task 6: Verify end-to-end integration and document

**Files:**
- Modify: `agent/context_pack/README.md`
- Modify: `agent/naming_sql_selector/README.md`
- Modify: `README.md`

- [ ] Document the lightweight Boolean route, fail-open all-resource behavior, single-build invariant, and downstream consumers.
- [ ] Run focused ContextPack, ValueLogic, NamingSQL, typed-context, and planner suites.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q`.
- [ ] Run `git diff --check`, inspect `git status --short`, and confirm the pre-existing `tests/test_context_pack_ootb.py` modification was not staged or altered by this work.
- [ ] Commit `docs: document value logic context pack flow` and hand off public signatures and verification evidence.
