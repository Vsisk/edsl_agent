# Generate Node Operation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, optionally LLM-enhanced operation that generates one validated EDSL tree node and an RFC 6902 add patch.

**Architecture:** Keep the root `models.py` as the node-schema source, with a local ID-generator compatibility module and safe default factories. Put operation contracts, path resolution, routing, field generation, assembly, validation, and patch building in one focused operation module with small independently tested classes. Use injected callables for the two narrow LLM boundaries and deterministic local fallbacks.

**Tech Stack:** Python 3.11, Pydantic v2, jsonpath-ng, unittest/pytest, existing prompt manager and LLM adapter.

---

## File Map

- Create `common/__init__.py`: compatibility package for shared model utilities.
- Create `common/utils/__init__.py`: utility package export boundary.
- Create `common/utils/id_generator.py`: 20-character timestamp/random node ID generation expected by `models.py`.
- Modify `models.py`: eliminate shared mutable defaults and clean `iter_local_context` for disallowed types.
- Create `agent/generate_node_operation.py`: operation contracts and the complete staged pipeline.
- Modify `prompt.json`: add the two constrained prompt templates.
- Create `tests/test_tree_node_models.py`: model import, cleanup, defaults, and AB alignment tests.
- Create `tests/test_generate_node_operation.py`: collaborator unit tests and operation acceptance tests.
- Create `tests/test_generate_node_operation_integration.py`: patch-application end-to-end test.

### Task 1: Make node models importable and safe

**Files:**
- Create: `common/__init__.py`
- Create: `common/utils/__init__.py`
- Create: `common/utils/id_generator.py`
- Modify: `models.py:751-837`
- Test: `tests/test_tree_node_models.py`

- [ ] **Step 1: Write failing model tests**

```python
from models import TreeNodeTerm


def test_simple_leaf_clears_iter_local_context():
    node = TreeNodeTerm.model_validate({
        "tree_node_type": "simple_leaf",
        "iter_local_context": [{"name": "illegal"}],
    })
    assert node.iter_local_context is None


def test_parent_defaults_are_not_shared():
    first = TreeNodeTerm(tree_node_type="parent")
    second = TreeNodeTerm(tree_node_type="parent")
    first.children.append(TreeNodeTerm(tree_node_type="simple_leaf"))
    assert second.children == []


def test_ab_content_type_matches_outer_type():
    node = TreeNodeTerm.model_validate({
        "tree_node_type": "ab_pivot_table",
        "ab_content": {},
    })
    assert node.ab_content.tree_node_type == "ab_pivot_table"
```

- [ ] **Step 2: Run model tests and verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_tree_node_models.py -v`

Expected: collection initially fails because `common.utils.id_generator` is missing; after the compatibility module exists, cleanup/default-isolation assertions fail until the model validator is corrected.

- [ ] **Step 3: Add the local ID generator and factory-based special configs**

```python
# common/utils/id_generator.py
from datetime import datetime
import secrets


def generate_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    suffix = f"{secrets.randbelow(100_000_000):08d}"
    return f"{timestamp}{suffix}"
```

Represent each `TreeNodeTerm.Config.special_configs` entry as a callable factory, for example `"children": list` and `"data_expression": DataExpressionTerm`, and call the factory when a field is missing. Add `iter_local_context` to `optional_field_names`.

- [ ] **Step 4: Run model tests and verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_tree_node_models.py -v`

Expected: all model tests pass.

### Task 2: Define contracts and resolve parent paths

**Files:**
- Create: `agent/generate_node_operation.py`
- Test: `tests/test_generate_node_operation.py`

- [ ] **Step 1: Write failing contract and path tests**

```python
def test_resolves_parent_jsonpath_to_children_and_patch_paths(sample_tree):
    result = PathResolver().resolve(sample_tree, "$.mapping_content")
    assert result.parent_path == "$.mapping_content"
    assert result.children_path == "$.mapping_content.children"
    assert result.patch_path == "/mapping_content/children/-"


def test_rejects_leaf_as_parent(sample_tree):
    with pytest.raises(OperationFailure) as error:
        PathResolver().resolve(sample_tree, "$.mapping_content.children[0]")
    assert error.value.code == "TARGET_PARENT_CANNOT_HAVE_CHILDREN"
```

Also cover malformed, unsupported, missing, and ambiguous paths.

- [ ] **Step 2: Run path tests and verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py -k "path or parent" -v`

Expected: import fails because the operation module does not exist.

- [ ] **Step 3: Implement contracts, failure type, and resolver**

Define `GenerateNodeOperationInput`, `GenerateNodeOperationOutput`, `ValidationErrorDetail`, `ResolvedNodePath`, and `OperationFailure` with the approved fields. Accept only simple JSONPath property/index segments, use `jsonpath_ng.parse` for lookup, require one dictionary match, and convert segments to an escaped RFC 6901 JSON Pointer ending in `/children/-`.

- [ ] **Step 4: Run path tests and verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py -k "path or parent" -v`

Expected: all selected tests pass.

### Task 3: Route and generate node fields

**Files:**
- Modify: `agent/generate_node_operation.py`
- Test: `tests/test_generate_node_operation.py`

- [ ] **Step 1: Write failing routing and field-generation tests**

```python
@pytest.mark.parametrize(("query", "expected"), [
    ("生成账户ID字段", "simple_leaf"),
    ("生成账户信息父节点", "parent"),
    ("生成账单明细列表节点", "parent_list"),
    ("生成费用透视表节点", "ab_pivot_table"),
    ("生成两级明细表节点", "ab_two_level_table"),
])
def test_routes_supported_node_types(query, expected):
    assert NodeTypeRouter().route(query).tree_node_type == expected
```

Add focused assertions for common-field allowlisting, stable XML names, explicit XML empty-field modes, logic-area IDs, money/time types, list defaults, and AB content classes.

- [ ] **Step 2: Run routing/field tests and verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py -k "route or common or type_specific" -v`

Expected: failures report missing router and generator implementations.

- [ ] **Step 3: Implement deterministic router and generators**

Use ordered keyword groups for two-level table, pivot, list, and parent, falling back to simple leaf. Generate common fields from an explicit identifier or a stable business-token map, store XML empty-field behavior in the model's `xml_empty_field_type`, and create type-specific model instances from `models.py`.

- [ ] **Step 4: Run routing/field tests and verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py -k "route or common or type_specific" -v`

Expected: all selected tests pass.

### Task 4: Assemble, validate, and build the operation result

**Files:**
- Modify: `agent/generate_node_operation.py`
- Test: `tests/test_generate_node_operation.py`

- [ ] **Step 1: Write failing operation acceptance tests**

```python
def test_generates_simple_leaf_and_add_patch(sample_tree):
    result = GenerateNodeOperation().execute(GenerateNodeOperationInput(
        query="生成账户ID字段",
        node_path="$.mapping_content",
        edsl_tree=sample_tree,
    ))
    assert result.success is True
    assert result.generated_node["tree_node_type"] == "simple_leaf"
    assert result.patch == {
        "op": "add",
        "path": "/mapping_content/children/-",
        "value": result.generated_node,
    }


def test_failure_never_returns_partial_patch(sample_tree):
    result = GenerateNodeOperation().execute(GenerateNodeOperationInput(
        query="生成字段",
        node_path="$.mapping_content.children[0]",
        edsl_tree=sample_tree,
    ))
    assert result.success is False
    assert result.failure_reason == "TARGET_PARENT_CANNOT_HAVE_CHILDREN"
    assert result.generated_node is None
    assert result.patch is None
```

Cover all five success types, empty XML name, schema validation errors, and illegal draft-field cleanup.

- [ ] **Step 2: Run acceptance tests and verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py -k "generates or failure or empty_xml" -v`

Expected: failures report missing `execute`, assembler, or patch-builder behavior.

- [ ] **Step 3: Implement assembler, validator boundary, patch builder, and orchestration**

`NodeAssembler` merges the three field groups. `GenerateNodeOperation.execute` runs the pipeline in order, calls `TreeNodeTerm.model_validate`, serializes with `model_dump(exclude_none=True)`, then builds the patch. Catch `OperationFailure` and Pydantic `ValidationError` separately and return structured failure output without a node or patch.

- [ ] **Step 4: Run all operation unit tests and verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py -v`

Expected: all operation unit tests pass.

### Task 5: Add narrow prompts and injected LLM fallbacks

**Files:**
- Modify: `prompt.json`
- Modify: `agent/generate_node_operation.py`
- Test: `tests/test_generate_node_operation.py`
- Test: `tests/test_planner_prompt.py`

- [ ] **Step 1: Write failing prompt and fallback tests**

```python
def test_invalid_llm_route_falls_back_to_local_rules(sample_tree):
    operation = GenerateNodeOperation(route_llm=lambda query: {"tree_node_type": "unknown"})
    result = operation.execute(GenerateNodeOperationInput(
        query="生成费用透视表节点",
        node_path="$.mapping_content",
        edsl_tree=sample_tree,
    ))
    assert result.success is True
    assert result.route_result["tree_node_type"] == "ab_pivot_table"
    assert result.route_result["source"] == "local"
```

Add prompt-render tests proving `node_type_route_prompt` and `common_node_field_prompt` render with only `query`.

- [ ] **Step 2: Run prompt/fallback tests and verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py tests/test_planner_prompt.py -k "llm or node_type_route_prompt or common_node_field_prompt" -v`

Expected: prompt keys and injected collaborator behavior are missing.

- [ ] **Step 3: Add prompt templates and constrained injected-callable adapters**

Add both Chinese prompt entries to `prompt.json`, each requiring `{{query}}` and strict JSON-only output. Validate injected results against route/common-field Pydantic models; on exceptions or invalid payloads, use local results.

- [ ] **Step 4: Run prompt/fallback tests and verify GREEN**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation.py tests/test_planner_prompt.py -k "llm or node_type_route_prompt or common_node_field_prompt" -v`

Expected: all selected tests pass.

### Task 6: Verify patch application and regression safety

**Files:**
- Create: `tests/test_generate_node_operation_integration.py`

- [ ] **Step 1: Write the failing end-to-end patch test**

```python
def test_generated_patch_appends_a_valid_tree_node(sample_tree):
    result = GenerateNodeOperation().execute(GenerateNodeOperationInput(
        query="生成账户ID字段",
        node_path="$.mapping_content",
        edsl_tree=sample_tree,
    ))
    patched = apply_add_patch(deepcopy(sample_tree), result.patch)
    inserted = patched["mapping_content"]["children"][-1]
    assert TreeNodeTerm.model_validate(inserted).tree_node_type == "simple_leaf"
```

- [ ] **Step 2: Run the integration test and verify RED**

Run: `.venv/Scripts/python -m pytest tests/test_generate_node_operation_integration.py -v`

Expected: the patch helper or an uncovered serialization behavior initially fails.

- [ ] **Step 3: Add the minimal RFC 6902 test helper and fix only exposed production defects**

The helper traverses decoded JSON Pointer segments, treats `-` as list append, and applies only the operation's supported add shape. Any production correction must be preceded by a focused failing regression test.

- [ ] **Step 4: Run focused and full verification**

Run: `.venv/Scripts/python -m pytest tests/test_tree_node_models.py tests/test_generate_node_operation.py tests/test_generate_node_operation_integration.py -v`

Expected: all new tests pass.

Run: `.venv/Scripts/python -m pytest -q`

Expected: the complete existing and new test suite passes with no failures.
