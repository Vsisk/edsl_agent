# LLM-Driven Node Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove production keyword interpretation from GenerateNode and ModifyNode and replace it with validated, prompt-backed LLM semantic calls that fail explicitly without fallback.

**Architecture:** Introduce typed LLM semantic components around the existing `generate_by_llm()` gateway. GenerateNode performs route, common-field, and content-intent calls; ModifyNode performs intent and plan calls. Local code retains model construction, migration, destructive enforcement, validation, and patch creation.

**Tech Stack:** Python 3.13, Pydantic v2, existing `generate_by_llm`, prompt manager, pytest.

---

### Task 1: LLM-driven GenerateNode semantics

**Files:**
- Modify: `agent/generate_node_operation.py`
- Modify: `tests/test_generate_node_operation.py`

- [ ] Write failing tests proving `NodeTypeRouter` and `CommonFieldGenerator` call injected LLM gateways, reject invalid payloads with component error codes, and never fall back to keyword rules.
- [ ] Run `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py -k "llm_router or llm_common or no_keyword_fallback" -v` and verify RED.
- [ ] Replace `_RULES` and `_NAME_TERMS` with gateway-backed implementations using these contracts:

```python
class NodeContentIntent(BaseModel):
    tree_node_type: NodeType
    data_type: Literal["simple_string", "time", "money"] = "simple_string"
    requires_expression_generation: bool = False
    requires_data_source_generation: bool = False
    expression_query: str | None = None
    data_source_query: str | None = None
    ab_content_query: str | None = None
    reason: str = ""
```

- [ ] Add `NodeContentIntentGenerator`; make `TypeSpecificFieldGenerator` consume intent rather than inspect query; remove money/time keyword lists.
- [ ] Run the focused tests and all GenerateNode tests; expect PASS.

### Task 2: LLM-driven ModifyNode semantics

**Files:**
- Modify: `agent/modify_node_operation.py`
- Modify: `tests/test_modify_node_operation.py`

- [ ] Write failing tests proving intent and plan components call injected gateways, invalid/raised responses fail with `MODIFY_INTENT_ROUTE_FAILED` or `MODIFY_PLAN_GENERATION_FAILED`, and query keywords no longer produce a local result.
- [ ] Write failing tests proving datatype/common updates and destructive authorization come only from `NodeModifyPlan` fields.
- [ ] Run `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -k "llm_semantic or no_keyword_fallback or structured_plan" -v` and verify RED.
- [ ] Add `destructive_authorized: bool = False` and `rebuild_node: bool = False` to `NodeModifyPlan`.
- [ ] Replace `_TYPE_PATTERNS`, `_CATEGORY_RULES`, and extraction regexes with gateway-backed `ModifyIntentRouter` and `ModifyPlanGenerator`.
- [ ] Make `ModifyExecutor` apply validated `type_field_updates`; make `DestructiveChangeGuard` consume `destructive_authorized`; make migration rebuild consume `rebuild_node`.
- [ ] Run all ModifyNode tests; expect PASS.

### Task 3: Production gateways and prompts

**Files:**
- Modify: `agent/generate_node_operation.py`
- Modify: `agent/modify_node_operation.py`
- Modify: `prompt.json`
- Modify: `tests/test_planner_prompt.py`

- [ ] Write failing tests that monkeypatch the module-level LLM gateway and assert the correct prompt keys and variables for all five semantic calls.
- [ ] Write failing prompt-render tests for `node_content_intent_prompt` and the strengthened existing four prompts.
- [ ] Implement default gateways as narrow calls to `generate_by_llm(prompt_key, **variables)`; injected callables remain supported for tests.
- [ ] Update prompts with strict JSON allowlists, full input context, no final-node/patch authority, and explicit destructive/rebuild fields.
- [ ] Run semantic and prompt tests; expect PASS.

### Task 4: Rewrite acceptance fixtures and verify regressions

**Files:**
- Modify: `tests/test_generate_node_operation.py`
- Modify: `tests/test_generate_node_operation_integration.py`
- Modify: `tests/test_modify_node_operation.py`
- Modify: `tests/test_modify_node_operation_integration.py`

- [ ] Replace production keyword-dependent fixtures with deterministic fake semantic gateways returning typed payloads for each scenario.
- [ ] Verify LLM exception/invalid JSON cases return no node or patch and do not call any local semantic fallback.
- [ ] Run `.venv/Scripts/python -m json.tool prompt.json`; expect valid JSON.
- [ ] Run `.venv/Scripts/python -m pytest -q`; expect the complete suite to pass with only documented skips/warnings.
