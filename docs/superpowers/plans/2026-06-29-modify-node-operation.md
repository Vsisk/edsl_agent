# Modify Node Operation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe single-node modification operation supporting common/type-field edits, validated type migration, destructive-change protection, and applicable replace patches.

**Architecture:** Extend the generate operation's simple JSONPath machinery with a neutral resolution primitive, then compose its type defaults inside a new modify pipeline. The modify pipeline resolves context, routes intent, builds a business plan, executes updates or migrations on a deep copy, validates through `TreeNodeTerm`, guards destructive changes, and emits one whole-node RFC 6902 replace patch.

**Tech Stack:** Python 3.13, Pydantic v2, jsonpath-ng, pytest/unittest, existing `TreeNodeTerm`, `TypeSpecificFieldGenerator`, prompt manager, and injectable expression/complex-content adapters.

---

## File Map

- Modify `agent/generate_node_operation.py`: expose container-neutral simple JSONPath resolution and node serialization without changing generate behavior.
- Create `agent/modify_node_operation.py`: contracts, resolver, intent router, plan generator, migration planner, executor, destructive guard, semantic validator, patch builder, and operation orchestration.
- Modify `prompt.json`: add `modify_intent_route_prompt` and `modify_plan_prompt`.
- Create `tests/test_modify_node_operation.py`: unit and acceptance coverage.
- Create `tests/test_modify_node_operation_integration.py`: applied replace-patch verification.
- Modify `tests/test_planner_prompt.py`: prompt rendering assertions.

### Task 1: Resolve a target node and its context

**Files:**
- Modify: `agent/generate_node_operation.py`
- Create: `agent/modify_node_operation.py`
- Create: `tests/test_modify_node_operation.py`

- [ ] **Step 1: Write failing resolver tests**

```python
def test_resolves_target_parent_ancestors_and_pointer(sample_tree):
    result = NodeResolver().resolve(sample_tree, "$.mapping_content.children[1]")
    assert result.current_node["xml_name_property"]["xml_name"] == "DETAILS"
    assert result.parent_node["tree_node_type"] == "parent"
    assert result.node_pointer == "/mapping_content/children/1"
    assert result.ancestor_nodes[0]["tree_node_type"] == "parent"


def test_missing_target_uses_target_node_error(sample_tree):
    with pytest.raises(OperationFailure) as error:
        NodeResolver().resolve(sample_tree, "$.mapping_content.children[9]")
    assert error.value.code == "TARGET_NODE_NOT_FOUND"
```

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -k resolve -v`

Expected: import fails because `agent.modify_node_operation` is absent.

- [ ] **Step 3: Implement neutral path resolution and NodeResolver**

Add `PathResolver.resolve_value(edsl_tree, node_path)` returning normalized JSONPath, JSON Pointer, and one resolved value. Keep `PathResolver.resolve()` responsible for the generate-only container check. `NodeResolver` rejects non-dictionary targets, walks path prefixes, and gathers ancestor `local_context` and `iter_local_context` entries.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -k resolve -v`

Expected: resolver tests pass and GenerateNode path tests remain green.

### Task 2: Route modification intent and build local plans

**Files:**
- Modify: `agent/modify_node_operation.py`
- Test: `tests/test_modify_node_operation.py`

- [ ] **Step 1: Write failing intent/plan tests**

```python
@pytest.mark.parametrize(("query", "intent"), [
    ("把 XML 名称改成 ACCT_ID 并修改注释", "set_common_field"),
    ("修改取值表达式", "modify_expression"),
    ("改成金额类型，精度 2", "modify_datatype"),
    ("修改循环数据源", "modify_data_source"),
    ("修改 local context", "modify_context"),
    ("修改透视表 group by", "modify_ab_content"),
    ("改成列表节点", "change_node_type"),
])
def test_routes_modify_intent(query, intent):
    assert ModifyIntentRouter().route(query).intent_type == intent


def test_plan_extracts_common_updates():
    intent = ModifyIntentRouter().route("XML 名称改成 ACCT_ID，注释改成账户ID")
    plan = ModifyPlanGenerator().generate(intent, "XML 名称改成 ACCT_ID，注释改成账户ID")
    assert plan.common_field_updates["xml_name_property"]["xml_name"] == "ACCT_ID"
    assert plan.common_field_updates["annotation"] == "账户ID"
```

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -k "intent or plan" -v`

Expected: missing router/plan classes fail.

- [ ] **Step 3: Implement Pydantic contracts, ordered local rules, and update allowlists**

Define `ModifyNodeOperationInput`, `ModifyNodeOperationOutput`, `ModifyIntent`, `NodeModifyPlan`, and `NodeTypeMigrationPlan` with factory defaults. Route explicit type changes first, then AB/context/data-source/expression/datatype/common intents. Extract only explicit common values, direct expression text, and datatype configuration.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -k "intent or plan" -v`

Expected: all selected tests pass.

### Task 3: Plan and execute type migrations

**Files:**
- Modify: `agent/modify_node_operation.py`
- Test: `tests/test_modify_node_operation.py`

- [ ] **Step 1: Write failing migration tests**

```python
def test_parent_to_parent_list_preserves_children(sample_parent):
    plan = MigrationPlanner().plan(sample_parent, "parent_list")
    candidate, report = ModifyExecutor().migrate(sample_parent, plan, "改成列表节点")
    assert candidate["children"] == sample_parent["children"]
    assert candidate["local_context"] == sample_parent["local_context"]
    assert "data_source" in candidate


def test_simple_leaf_to_pivot_initializes_matching_ab_content(sample_leaf):
    plan = MigrationPlanner().plan(sample_leaf, "ab_pivot_table")
    candidate, report = ModifyExecutor().migrate(sample_leaf, plan, "改成透视表")
    validated = TreeNodeTerm.model_validate(candidate)
    assert validated.ab_content.tree_node_type == "ab_pivot_table"
```

Cover parent-list to parent, leaf to parent/list, pivot to two-level, and AB to non-AB policies.

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -k migration -v`

Expected: missing planner/executor migration behavior fails.

- [ ] **Step 3: Implement migration matrix using TypeSpecificFieldGenerator**

Preserve the six base fields and same node ID, initialize target fields through `TypeSpecificFieldGenerator.generate`, selectively copy compatible children/local context and AB `data_source`/`group_by_fields`, and record dropped/preserved/initialized fields in `MigrationReport`.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -k migration -v`

Expected: all migration tests pass.

### Task 4: Enforce destructive safety and execute field updates

**Files:**
- Modify: `agent/modify_node_operation.py`
- Test: `tests/test_modify_node_operation.py`

- [ ] **Step 1: Write failing destructive and field-update tests**

```python
def test_parent_with_children_cannot_become_leaf_without_authorization(sample_tree):
    result = ModifyNodeOperation().execute(ModifyNodeOperationInput(
        query="改成普通字段",
        node_path="$.mapping_content",
        edsl_tree=sample_tree,
    ))
    assert result.failure_reason == "DESTRUCTIVE_CHANGE_NOT_ALLOWED"
    assert result.patch_list == []


def test_authorized_clear_allows_parent_to_leaf(sample_tree):
    result = ModifyNodeOperation().execute(ModifyNodeOperationInput(
        query="删除并清空子节点，改成普通字段",
        node_path="$.mapping_content",
        edsl_tree=sample_tree,
        allow_destructive=True,
    ))
    assert result.success is True
    assert result.migration_report["children_action"] == "drop"
```

Add tests for XML/annotation, money datatype, injected expression adapter, adapter failure, unsupported complex edits, and failure-without-patch invariants.

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -k "destructive or xml or datatype or expression" -v`

Expected: operation orchestration and guard behavior are missing.

- [ ] **Step 3: Implement ModifyExecutor field updates, adapters, guard, validation, and operation**

Apply plans to `deepcopy(original_node)`. Invoke the expression adapter with a `ModifyAdapterContext`; map failures to `EXPRESSION_GENERATION_FAILED`. Validate the candidate with `TreeNodeTerm.model_validate`, reinsert serialized AB discriminator, compare destructive fields, enforce both authorization conditions, and return structured failures without patches.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py -v`

Expected: all ModifyNode unit/acceptance tests pass.

### Task 5: Build replace patches and add constrained prompts

**Files:**
- Modify: `agent/modify_node_operation.py`
- Modify: `prompt.json`
- Modify: `tests/test_planner_prompt.py`
- Test: `tests/test_modify_node_operation.py`

- [ ] **Step 1: Write failing patch/prompt/LLM fallback tests**

```python
def test_success_returns_whole_node_replace_patch(sample_tree):
    result = ModifyNodeOperation().execute(ModifyNodeOperationInput(
        query="XML 名称改成 ACCT_ID",
        node_path="$.mapping_content.children[0]",
        edsl_tree=sample_tree,
    ))
    assert result.patch_list == [{
        "op": "replace",
        "path": "/mapping_content/children/0",
        "value": result.modified_node,
    }]
```

Add prompt render assertions and invalid/unavailable LLM fallback assertions.

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py tests/test_planner_prompt.py -k "patch or modify_intent_route_prompt or modify_plan_prompt or llm" -v`

Expected: prompt keys or patch builder behavior are missing.

- [ ] **Step 3: Implement ModifyPatchBuilder and two narrow prompt entries**

Emit one replace patch only after validation and guard success. Add strict JSON-only prompts using `{{query}}` and current-node JSON variables; validate injected payloads with the intent/plan models and fall back to local rules on any external failure.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation.py tests/test_planner_prompt.py -k "patch or modify_intent_route_prompt or modify_plan_prompt or llm" -v`

Expected: all selected tests pass.

### Task 6: Apply the patch end to end and run regression verification

**Files:**
- Create: `tests/test_modify_node_operation_integration.py`

- [ ] **Step 1: Write failing applied-patch test**

```python
def test_replace_patch_updates_tree_with_valid_node(sample_tree):
    result = ModifyNodeOperation().execute(ModifyNodeOperationInput(
        query="改成金额类型，精度 2",
        node_path="$.mapping_content.children[0]",
        edsl_tree=sample_tree,
    ))
    patched = apply_replace_patch(deepcopy(sample_tree), result.patch_list[0])
    node = patched["mapping_content"]["children"][0]
    assert TreeNodeTerm.model_validate(node).data_type_config.data_type == "money"
```

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_modify_node_operation_integration.py -v`

Expected: missing patch helper or uncovered patch semantics fail.

- [ ] **Step 3: Add the minimal RFC 6902 replace helper and correct only test-exposed defects**

Decode RFC 6901 segments, traverse dictionaries/lists, replace the final target, and validate the inserted node. Any production correction requires its own focused failing regression test first.

- [ ] **Step 4: Run complete verification**

Run: `.venv/Scripts/python -m json.tool prompt.json`

Expected: valid JSON.

Run: `.venv/Scripts/python -m pytest -q`

Expected: all existing GenerateNode and new ModifyNode tests pass, with only documented skips/warnings.
