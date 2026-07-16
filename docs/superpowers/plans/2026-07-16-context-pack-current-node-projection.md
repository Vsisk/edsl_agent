# ContextPack Current-Node Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose each recalled current-tree node's complete top-level data, including existing expressions, to downstream ContextPack prompt consumers while excluding its `children` subtree.

**Architecture:** Keep providers and ContextPack contracts unchanged. Extend only `ContextPackPromptRenderer` with a defensive node projection for current-tree node/field items, and preserve atomic item trimming under the existing character budget.

**Tech Stack:** Python 3.12, Pydantic 2, pytest

---

### Task 1: Project complete childless current-tree nodes

**Files:**
- Modify: `tests/test_context_pack_prompt_renderer.py`
- Modify: `agent/context_pack/prompt_renderer.py`

- [ ] **Step 1: Write failing projection tests**

Add tests that construct a `current_tree` field item whose `content.value` contains `data_expression`, `edsl_semi_struct`, an arbitrary configuration field, and nested `children`. Assert rendered JSON contains a `node` copy with every top-level field except `children`, does not mutate the source item, and does not add `node` to non-current-tree or local/iter items.

- [ ] **Step 2: Run the projection tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_context_pack_prompt_renderer.py -q`

Expected: FAIL because rendered items do not contain `node`.

- [ ] **Step 3: Implement the minimal projection**

Add a private renderer helper equivalent to:

```python
@staticmethod
def _project_node(section, item):
    if section.resource_name.value != "current_tree" or item.item_type not in {"node", "field"}:
        return None
    value = item.content.get("value")
    if not isinstance(value, dict):
        return None
    return {key: deepcopy(field_value) for key, field_value in value.items() if key != "children"}
```

Attach the result as `projection["node"]` only when it is not `None`.

- [ ] **Step 4: Run the projection tests and verify success**

Run: `.venv\Scripts\python.exe -m pytest tests/test_context_pack_prompt_renderer.py -q`

Expected: all tests PASS.

### Task 2: Preserve atomic trimming and report budget loss

**Files:**
- Modify: `tests/test_context_pack_prompt_renderer.py`
- Modify: `agent/context_pack/prompt_renderer.py`

- [ ] **Step 1: Write a failing budget test**

Add a test with a projected current-tree node too large for `max_chars`. Assert the entire item is absent, output remains valid JSON, and warnings include `CONTEXT_PACK_PROMPT_TRIMMED`.

- [ ] **Step 2: Run the budget test and verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_context_pack_prompt_renderer.py -q`

Expected: FAIL because current overflow removal does not add the trimming warning.

- [ ] **Step 3: Implement trimming warning propagation**

When adding an item makes the serialized value exceed `max_chars`, remove the item, append `CONTEXT_PACK_PROMPT_TRIMMED` once to the top-level warnings, and return `_bounded_dump(value)`. Keep item projection atomic and do not slice its serialized JSON.

- [ ] **Step 4: Run focused and downstream tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_context_pack_prompt_renderer.py tests/test_value_logic_generator.py tests/test_llm_planner.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Run repository hygiene checks**

Run: `git diff --check`

Expected: no output and exit code 0.
