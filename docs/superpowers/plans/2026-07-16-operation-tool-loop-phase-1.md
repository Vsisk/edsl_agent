# Operation Tool Loop Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the default mapping-content operation graph orchestration with a registered, version-safe, multi-step tool loop while reusing existing tree indexing and action adapters.

**Architecture:** Add strict tool-call and trace models, a registry, a stateful mapping-content runtime, and an LLM-driven loop inside the existing `agent/operation_orchestration` package. Keep legacy generator/executor injection compatibility, but make `OperationOrchestrator` default to the new loop.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, existing `generate_by_llm`, `build_node_index`, `OperationActionAdapter`.

---

### Task 1: Tool models and registry

**Files:**
- Modify: `agent/operation_orchestration/models.py`
- Create: `agent/operation_orchestration/registry.py`
- Modify: `agent/operation_orchestration/__init__.py`
- Test: `tests/test_operation_tool_registry.py`

- [ ] **Step 1: Write failing registry tests**

```python
def test_registry_validates_and_dispatches_strict_input():
    registry = OperationToolRegistry()
    registry.register(OperationToolSpec(name="sample", description="sample", input_model=SampleInput), handler)
    assert registry.execute("sample", {"value": 2}, context) == {"value": 3}
    with pytest.raises(ValueError, match="invalid tool input"):
        registry.execute("sample", {"value": 2, "extra": True}, context)

def test_registry_rejects_duplicate_names():
    registry.register(spec, handler)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec, handler)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_operation_tool_registry.py -q`
Expected: collection failure because registry classes do not exist.

- [ ] **Step 3: Implement strict models and registry**

Add `ToolDecision`, per-tool input models, `ToolCallTrace`, `OperationToolSpec`, and `OperationToolLoopResponse` to `models.py`. Implement unique snake-case registration, schema export, strict input validation, and handler dispatch in `registry.py`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/test_operation_tool_registry.py -q`
Expected: all registry tests pass.

### Task 2: Version-safe mapping-content runtime

**Files:**
- Create: `agent/operation_orchestration/runtime.py`
- Modify: `agent/operation_orchestration/node_index.py`
- Test: `tests/test_operation_tool_runtime.py`

- [ ] **Step 1: Write failing runtime search and authorization tests**

```python
def test_search_filters_candidates_by_intent_and_authorizes_current_version():
    runtime = OperationToolRuntime(tree(), action_adapter=RecordingAdapter())
    result = runtime.execute("search_nodes", {"query": "account", "intent_type": "modify_node", "limit": 10})
    assert [item["node_id"] for item in result["candidates"]] == ["acct-id"]
    assert result["version"] == 0

def test_mutation_rejects_unsearched_or_stale_candidate():
    with pytest.raises(ValueError, match="authorized search candidate"):
        runtime.execute("modify_node", target_args("acct-id", "$.children[0]"))
    searched = runtime.execute("search_nodes", search_args("modify_node"))
    runtime.execute("modify_node", mutation_args(searched["candidates"][0]))
    with pytest.raises(ValueError, match="authorized search candidate"):
        runtime.execute("modify_node", mutation_args(searched["candidates"][0]))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_operation_tool_runtime.py -q`
Expected: collection failure because `OperationToolRuntime` does not exist.

- [ ] **Step 3: Implement runtime and built-in handlers**

Runtime deep-copies the input tree, builds the existing node index, registers `search_nodes`, four mutation tools, and `finish`, validates exact candidate ID/path/intent/version, dispatches to `OperationActionAdapter`, validates adapter output using a rebuilt index, commits atomically, increments version, clears search grants, and appends executed `Operation` records.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/test_operation_tool_runtime.py tests/test_operation_action_adapter.py tests/test_operation_node_index.py -q`
Expected: all selected tests pass.

### Task 3: LLM tool loop and prompt

**Files:**
- Create: `agent/operation_orchestration/tool_loop.py`
- Modify: `prompt.json`
- Test: `tests/test_operation_tool_loop.py`

- [ ] **Step 1: Write failing loop tests**

```python
def test_loop_executes_search_create_search_expression_and_finish():
    decisions = iter([
        {"tool_name": "search_nodes", "arguments": {"query": "parent", "intent_type": "create_node", "limit": 10}},
        {"tool_name": "create_node", "arguments": selected_parent_args()},
        {"tool_name": "search_nodes", "arguments": {"query": "new field", "intent_type": "generate_expression", "limit": 10}},
        {"tool_name": "generate_expression", "arguments": selected_new_field_args()},
        {"tool_name": "finish", "arguments": {}},
    ])
    response = OperationToolLoop(llm_gateway=lambda **_: next(decisions), action_adapter=adapter).run(request)
    assert response.success
    assert [op.intent_type for op in response.operations] == ["create_node", "generate_expression"]
    assert response.version == 2

def test_loop_fails_safely_at_max_steps():
    response = loop_always_search.run(request.model_copy(update={"max_steps": 2}))
    assert not response.success
    assert response.error_message == "operation tool loop exceeded max_steps=2"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_operation_tool_loop.py -q`
Expected: collection failure because `OperationToolLoop` does not exist.

- [ ] **Step 3: Implement loop and prompt**

Render `operation_tool_loop_prompt` with authoritative query, bounded current tree summary, JSON tool schemas, and bounded call history. Strictly parse one decision per round, execute through runtime, stop only on `finish`, and convert gateway/schema/runtime failures into stable responses with trace.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/test_operation_tool_loop.py -q`
Expected: all loop tests pass.

### Task 4: Switch the default orchestrator path

**Files:**
- Modify: `agent/operation_orchestration/orchestrator.py`
- Modify: `agent/operation_orchestration/__init__.py`
- Modify: `tests/test_operation_orchestrator.py`

- [ ] **Step 1: Write failing default-path compatibility tests**

```python
def test_default_facade_delegates_to_tool_loop_and_preserves_input():
    loop = RecordingToolLoop(success_response)
    original = deepcopy(tree)
    result = OperationOrchestrator(tool_loop=loop).run("multi task", tree, "S", "P", max_steps=8)
    assert result is success_response
    assert loop.request.target_tree == original
    assert tree == original

def test_legacy_generator_executor_injection_remains_supported():
    result = OperationOrchestrator(generator=generator, executor=executor).run("legacy", tree)
    assert result.success
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_operation_orchestrator.py -q`
Expected: default tool-loop injection test fails because `tool_loop` and `max_steps` are unsupported.

- [ ] **Step 3: Implement default tool-loop facade**

Construct `OperationToolLoop` only for the default path, forward a strict `OperationToolLoopRequest`, return the tool-loop response, and retain the explicit legacy path when generator or executor dependencies are supplied.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/test_operation_orchestrator.py tests/test_operation_executor.py tests/test_operation_generator.py tests/test_operation_locator.py -q`
Expected: tool-loop and legacy orchestration tests pass.

### Task 5: Regression verification

**Files:**
- Modify only if a regression exposes a scoped compatibility issue.

- [ ] **Step 1: Run focused orchestration suite**

Run: `pytest tests/test_operation_*.py -q`
Expected: all operation orchestration tests pass.

- [ ] **Step 2: Run full suite**

Run: `pytest -q`
Expected: all repository tests pass except documented skips.

- [ ] **Step 3: Inspect scope and diff quality**

Run: `git diff --check` and `git status --short`
Expected: no whitespace errors and only phase-one implementation/test/prompt/plan files are modified.
