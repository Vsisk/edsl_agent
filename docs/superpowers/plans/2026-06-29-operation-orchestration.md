# Operation Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested orchestration layer that decomposes one natural-language request into single-node operations, locates initial targets, and executes the dependency graph through existing node capabilities.

**Architecture:** A new `agent.operation_orchestration` package owns contracts, DFS indexing, LLM decomposition/location, action adaptation, topological execution, and the public facade. Existing generation, modification, and expression implementations remain behind `OperationActionAdapter`; only deterministic deletion and minimal AB-parent compatibility are added locally.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, `jsonpath-ng`, existing `generate_by_llm`/PromptManager, existing node-operation modules.

---

## File Map

- Create `agent/operation_orchestration/models.py`: public models and graph validation/topological sorting.
- Create `agent/operation_orchestration/node_index.py`: DFS candidate extraction and intent filtering.
- Create `agent/operation_orchestration/generator.py`: LLM operation decomposition and container-query enrichment.
- Create `agent/operation_orchestration/locator.py`: candidate-constrained semantic location and create-root fallback.
- Create `agent/operation_orchestration/action_adapter.py`: existing-action adapters, patch application, and local deletion.
- Create `agent/operation_orchestration/executor.py`: dependency resolution and fail-fast execution.
- Create `agent/operation_orchestration/orchestrator.py`: unified public entry point.
- Create `agent/operation_orchestration/__init__.py`: stable public exports.
- Modify `agent/generate_node_operation.py`: accept all required container types as create parents.
- Modify `prompt.json`: add generator and locator prompt contracts.
- Modify `tests/test_planner_prompt.py`: assert the two new prompt constraints.
- Create six focused orchestration test modules listed below.

### Task 1: Operation contracts and graph validation

**Files:**
- Create: `agent/operation_orchestration/models.py`
- Create: `tests/test_operation_models.py`

- [x] **Step 1: Write failing model and graph tests**

```python
import pytest
from pydantic import ValidationError

from agent.operation_orchestration.models import Operation, validate_and_sort_operations


def op(op_id, depends_on=None, target_from=None):
    return Operation(
        op_id=op_id,
        query=f"execute {op_id}",
        intent_type="create_node",
        depends_on=depends_on or [],
        target_from=target_from,
    )


def test_operation_uses_isolated_mutable_defaults():
    left = op("op_0")
    right = op("op_1")
    left.depends_on.append("external")
    assert right.depends_on == []


def test_graph_rejects_duplicate_missing_and_cyclic_dependencies():
    with pytest.raises(ValueError, match="duplicate op_id"):
        validate_and_sort_operations([op("op_0"), op("op_0")])
    with pytest.raises(ValueError, match="dependency not found"):
        validate_and_sort_operations([op("op_0", ["missing"])])
    with pytest.raises(ValueError, match="cyclic dependency"):
        validate_and_sort_operations([op("op_0", ["op_1"]), op("op_1", ["op_0"])])


def test_multiple_dependencies_require_valid_target_from():
    operations = [op("op_0"), op("op_1"), op("op_2", ["op_0", "op_1"])]
    with pytest.raises(ValueError, match="multiple dependencies require target_from"):
        validate_and_sort_operations(operations)


def test_topological_sort_is_stable_for_siblings():
    operations = [op("op_0"), op("op_1", ["op_0"]), op("op_2", ["op_0"])]
    assert [item.op_id for item in validate_and_sort_operations(operations)] == ["op_0", "op_1", "op_2"]
```

- [x] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_operation_models.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'agent.operation_orchestration'`.

- [x] **Step 3: Implement the contracts and stable Kahn sort**

```python
from typing import Literal
from pydantic import BaseModel, Field

IntentType = Literal["create_node", "modify_node", "generate_expression", "delete_node"]
OperationStatus = Literal["pending", "located", "executed", "failed"]


class Operation(BaseModel):
    op_id: str
    query: str
    intent_type: IntentType
    depends_on: list[str] = Field(default_factory=list)
    target_from: str | None = None
    target_jsonpath: str | None = None
    target_node_id: str | None = None
    output_node_id: str | None = None
    status: OperationStatus = "pending"
    error_message: str | None = None


class GenerateOperationsRequest(BaseModel):
    query: str
    target_tree: dict


class GenerateOperationsResponse(BaseModel):
    operations: list[Operation]


class LocateOperationRequest(BaseModel):
    operation: Operation
    target_tree: dict


class LocateOperationResponse(BaseModel):
    success: bool
    operation: Operation
    candidates: list[dict] = Field(default_factory=list)
    error_message: str | None = None


class ExecuteOperationsRequest(BaseModel):
    operations: list[Operation]
    target_tree: dict
    site_id: str | None = None
    project_id: str | None = None


class ExecuteOperationsResponse(BaseModel):
    success: bool
    target_tree: dict
    operations: list[Operation]
    error_message: str | None = None
```

Implement `validate_and_sort_operations()` with these exact checks before Kahn sorting: unique IDs, all dependencies exist, no self-dependency, `target_from` belongs to `depends_on`, and dependency count greater than one requires `target_from`. Use original list indices as the ready-queue ordering key.

- [x] **Step 4: Run model tests and verify GREEN**

Run: `python -m pytest tests/test_operation_models.py -q`

Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add agent/operation_orchestration/models.py tests/test_operation_models.py
git commit -m "feat: add operation orchestration contracts"
```

### Task 2: DFS node index and candidate filtering

**Files:**
- Create: `agent/operation_orchestration/node_index.py`
- Create: `tests/test_operation_node_index.py`

- [x] **Step 1: Write failing DFS tests**

```python
import pytest
from agent.operation_orchestration.node_index import build_node_index, is_valid_candidate


def tree():
    return {"mapping_content": {"node_id": "root", "tree_node_type": "parent", "xml_name_property": {"xml_name": "ROOT"}, "children": [{"node_id": "leaf", "tree_node_type": "simple_leaf", "xml_name_property": {"xml_name": "ACCT_ID"}}]}}


def test_build_node_index_records_exact_paths_and_parent_metadata():
    index = build_node_index(tree())
    assert index["root"].jsonpath == "$.mapping_content"
    assert index["leaf"].jsonpath == "$.mapping_content.children[0]"
    assert index["leaf"].parent_node_id == "root"
    assert index["leaf"].parent_xml_name == "ROOT"
    assert index["root"].child_count == 1


def test_create_filter_allows_required_containers_only():
    index = build_node_index(tree())
    assert is_valid_candidate("create_node", index["root"])
    assert not is_valid_candidate("create_node", index["leaf"])
    assert is_valid_candidate("delete_node", index["leaf"])


def test_duplicate_node_ids_are_rejected():
    payload = tree()
    payload["mapping_content"]["children"].append({"node_id": "leaf", "tree_node_type": "simple_leaf"})
    with pytest.raises(ValueError, match="duplicate node_id"):
        build_node_index(payload)
```

- [x] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_operation_node_index.py -q`

Expected: import fails because `node_index.py` does not exist.

- [x] **Step 3: Implement DFS and filters**

Define `NodeLocateCandidate(BaseModel)` with the requested fields and `CREATE_PARENT_TYPES` containing all five required types. Traverse dict properties in insertion order and list elements in index order. Build JSONPath segments with dot notation for identifier keys and quoted bracket notation for other keys; current production trees use identifier keys, yielding the acceptance paths above. A dictionary is indexed only when both `node_id` and `tree_node_type` are non-empty. Preserve DFS order in the returned dict.

```python
def is_valid_candidate(intent_type: str, candidate: NodeLocateCandidate) -> bool:
    if intent_type == "create_node":
        return candidate.tree_node_type in CREATE_PARENT_TYPES
    return intent_type in {"modify_node", "generate_expression", "delete_node"}
```

- [x] **Step 4: Run DFS tests and verify GREEN**

Run: `python -m pytest tests/test_operation_node_index.py -q`

Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add agent/operation_orchestration/node_index.py tests/test_operation_node_index.py
git commit -m "feat: index operation target nodes"
```

### Task 3: LLM operation generation and prompt

**Files:**
- Create: `agent/operation_orchestration/generator.py`
- Create: `tests/test_operation_generator.py`
- Modify: `prompt.json`
- Modify: `tests/test_planner_prompt.py`

- [x] **Step 1: Write failing generator tests**

Test an injected gateway returning: one create; `A -> B -> expression`; and `A -> {B, C}`. Assert IDs are normalized to `op_0...`, all target fields remain `None`, and A's query contains `需要包含子节点` only when downstream create operations target A. Also assert malformed graphs raise `ValueError` and the default gateway calls `generate_by_llm("operation_generator_prompt", query=..., target_tree_summary_json=...)`.

```python
def test_branch_parent_query_is_enriched_without_serializing_siblings():
    generator = OperationGenerator(llm_gateway=lambda query, summary: {"operations": [
        {"op_id": "op_0", "query": "新增A节点", "intent_type": "create_node", "depends_on": []},
        {"op_id": "op_1", "query": "在A下新增B", "intent_type": "create_node", "depends_on": ["op_0"]},
        {"op_id": "op_2", "query": "在A下新增C", "intent_type": "create_node", "depends_on": ["op_0"]},
    ]})
    result = generator.generate(GenerateOperationsRequest(query="新增A，并在A下新增B与C", target_tree={}))
    assert "需要包含子节点" in result.operations[0].query
    assert result.operations[1].depends_on == ["op_0"]
    assert result.operations[2].depends_on == ["op_0"]
```

- [x] **Step 2: Run generator tests and verify RED**

Run: `python -m pytest tests/test_operation_generator.py tests/test_planner_prompt.py -q`

Expected: generator import or new prompt assertions fail.

- [x] **Step 3: Implement generator and strict prompt**

Implement an injected gateway contract `(query: str, target_tree_summary: list[dict]) -> dict`; the default serializes the summary with `ensure_ascii=False` and calls `generate_by_llm`. Validate the response using `GenerateOperationsResponse`, overwrite IDs sequentially only when the response is already list-ordered, remap dependencies through the old-to-new ID map, clear all runtime fields, enrich container queries, then call `validate_and_sort_operations()` without reordering the response.

Add `operation_generator_prompt` requiring one node per operation, the four exact intent values, dependencies only when a target is produced upstream, `target_from` for multiple dependencies, no location/runtime fields, branch siblings depending on the same parent, and container-capability wording for newly created parents.

- [x] **Step 4: Run generator and prompt tests and verify GREEN**

Run: `python -m pytest tests/test_operation_generator.py tests/test_planner_prompt.py -q`

Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add agent/operation_orchestration/generator.py tests/test_operation_generator.py tests/test_planner_prompt.py prompt.json
git commit -m "feat: generate node-level operations"
```

### Task 4: Candidate-constrained locator and create fallback

**Files:**
- Create: `agent/operation_orchestration/locator.py`
- Create: `tests/test_operation_locator.py`
- Modify: `prompt.json`
- Modify: `tests/test_planner_prompt.py`

- [x] **Step 1: Write failing locator tests**

Cover successful selection, ID/path mismatch rejection, dependent-operation rejection, create-only root fallback on gateway exception or uncertain response, and no fallback for modify/expression/delete.

```python
def test_create_location_falls_back_to_root_container():
    locator = OperationLocator(llm_gateway=lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    response = locator.locate(LocateOperationRequest(operation=create_op(), target_tree=sample_tree()))
    assert response.success
    assert response.operation.target_node_id == "root"
    assert response.operation.target_jsonpath == "$.mapping_content"
    assert response.operation.status == "located"


def test_modify_location_does_not_fall_back():
    locator = OperationLocator(llm_gateway=lambda *_: {"selected_node_id": "missing", "selected_jsonpath": "$.invented", "confidence": "low", "reason": "uncertain"})
    response = locator.locate(LocateOperationRequest(operation=modify_op(), target_tree=sample_tree()))
    assert not response.success
    assert response.operation.status == "failed"
```

- [x] **Step 2: Run locator tests and verify RED**

Run: `python -m pytest tests/test_operation_locator.py tests/test_planner_prompt.py -q`

Expected: locator import or prompt assertions fail.

- [x] **Step 3: Implement locator and location-search prompt**

Define a strict `LocationSelection` model. Send only filtered candidate dumps, query, and intent to the injected gateway/default `generate_by_llm("operation_locator_prompt", ...)`. Accept confidence values `high`, `medium`, and `low`; treat low confidence as failure. Verify selected ID and exact path against the same candidate. On any selection/gateway failure, call `_fallback_create_root()` only for create; choose the first valid candidate whose `parent_node_id is None`. Return candidate dumps on all outcomes.

The prompt must explicitly state: select only supplied candidates, copy both ID and path verbatim from one candidate, never synthesize JSONPath, and return the strict four-field object.

- [x] **Step 4: Run locator and prompt tests and verify GREEN**

Run: `python -m pytest tests/test_operation_locator.py tests/test_planner_prompt.py -q`

Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add agent/operation_orchestration/locator.py tests/test_operation_locator.py tests/test_planner_prompt.py prompt.json
git commit -m "feat: locate operation targets"
```

### Task 5: Action adapter and deterministic deletion

**Files:**
- Create: `agent/operation_orchestration/action_adapter.py`
- Create: `tests/test_operation_action_adapter.py`
- Modify: `agent/operation_orchestration/node_index.py`
- Modify: `tests/test_operation_node_index.py`
- Modify: `agent/generate_node_operation.py`
- Modify: `tests/test_generate_node_operation.py`
- Modify: `prompt.json`
- Modify: `tests/test_planner_prompt.py`

- [x] **Step 1: Write failing adapter and AB-parent tests**

Inject fake existing operations/generator so tests assert exact request fields and real patch application. Add parameterized PathResolver tests for the three AB parent types. Test deletion removes one list element and returns its parent ID; root deletion must raise.

```python
def test_delete_node_returns_parent_and_updated_tree():
    adapter = OperationActionAdapter()
    result = adapter.delete_node("$.mapping_content.children[0]", sample_tree())
    assert result["parent_node_id"] == "root"
    assert result["target_tree"]["mapping_content"]["children"] == []


@pytest.mark.parametrize("node_type", ["ab_single_mapping_table", "ab_two_level_table", "ab_pivot_table"])
def test_path_resolver_accepts_ab_create_parent(node_type):
    payload = {"mapping_content": {"tree_node_type": node_type, "children": []}}
    assert PathResolver().resolve(payload, "$.mapping_content").children_path == "$.mapping_content.children"
```

- [x] **Step 2: Run adapter tests and verify RED**

Run: `python -m pytest tests/test_operation_action_adapter.py tests/test_generate_node_operation.py -q`

Expected: adapter import fails and AB parent assertions fail.

- [x] **Step 3: Implement adapter and minimal compatibility change**

Extend `PathResolver._CONTAINER_TYPES` to the five required create-parent types. Implement private pointer helpers that deep-copy input, accept only existing add/replace patch forms, and resolve exact list indices. Adapter methods must return dictionaries with `target_tree` plus `created_node_id` or `parent_node_id` where required. Create extracts the canonical ID from `result.generated_node["node_id"]` or `result.generated_node["field_id"]`; modify applies every patch in order; expression resolves the target and parent, calls `ValueLogicGenerator.generate(ValueLogicRequest(...))`, requires an expression result, and writes it to the schema-correct expression branch; delete rejects paths without a list parent and removes exactly one element.

Use the same JSONPath grammar for DFS output and action resolution, including `$` and quoted property segments. Forward optional site/project IDs through modify requests. Validate expression target capability: `simple_leaf` writes top-level `data_expression`; AB common fields write `data_source.data_expression`; containers and summary fields fail.

Extend the node index so known AB field slots are indexed by `field_id` with their real nested JSONPath, identity source, slot, and a synthetic common/summary field type. IDs remain globally unique across `node_id` and `field_id`.

Inside `GenerateNodeOperation`, route AB parents to an atomic AB-field branch instead of `children`. Add a strict `ab_field_placement_prompt` for the legal slots. Ambiguous placement defaults to `detail_fields` for single-mapping tables and `group_region.group_related_fields` for two-level/pivot tables. Reuse the common-field generator and Pydantic field models. A two-level summary creation atomically adds the same-name detail field plus a `SummaryField` whose `related_detail_field_name` is that name, emits one validated parent replacement patch, and reports the summary `field_id` as the created ID.

- [x] **Step 4: Run adapter tests and verify GREEN**

Run: `python -m pytest tests/test_operation_action_adapter.py tests/test_generate_node_operation.py -q`

Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add agent/operation_orchestration/action_adapter.py tests/test_operation_action_adapter.py agent/generate_node_operation.py tests/test_generate_node_operation.py
git commit -m "feat: adapt node actions for orchestration"
```

### Task 6: Topological executor and fail-fast partial results

**Files:**
- Create: `agent/operation_orchestration/executor.py`
- Create: `tests/test_operation_executor.py`

- [ ] **Step 1: Write failing executor tests**

Use recording fake locator/adapter objects. Test: roots invoke locator; dependent operations never invoke it; single/multiple dependency target resolution; output-ID rules; the second operation sees paths from a rebuilt index; and adapter failure returns prior tree changes while leaving later operations pending.

```python
def test_failure_stops_and_returns_partial_tree():
    operations = [create_op("op_0"), create_op("op_1", ["op_0"]), create_op("op_2", ["op_1"])]
    executor = OperationExecutor(locator=FakeLocator(), action_adapter=FailOnSecondAdapter())
    result = executor.execute(ExecuteOperationsRequest(operations=operations, target_tree=sample_tree()))
    assert not result.success
    assert [op.status for op in result.operations] == ["executed", "failed", "pending"]
    assert find_node(result.target_tree, "created-0") is not None


def test_dependent_operation_uses_upstream_output_without_locator():
    locator = RecordingLocator()
    executor = OperationExecutor(locator=locator, action_adapter=RecordingAdapter())
    result = executor.execute(ExecuteOperationsRequest(operations=[create_op("op_0"), create_op("op_1", ["op_0"])], target_tree=sample_tree()))
    assert locator.calls == ["op_0"]
    assert result.operations[1].target_node_id == result.operations[0].output_node_id
```

- [ ] **Step 2: Run executor tests and verify RED**

Run: `python -m pytest tests/test_operation_executor.py -q`

Expected: executor import fails.

- [ ] **Step 3: Implement execution**

Deep-copy operations and tree at entry. Validate/sort before mutation. For roots call locator and require success; for dependent operations use the sole dependency or `target_from`, require an executed upstream output ID, rebuild the current index, and populate both target fields. Dispatch to the four adapter methods, replace the current tree from the result, rebuild the index immediately, fill output ID according to intent, require it to be non-empty, and mark executed. Catch the first exception, mark only the current operation failed, preserve unvisited statuses, and return the partial tree.

- [ ] **Step 4: Run executor tests and verify GREEN**

Run: `python -m pytest tests/test_operation_executor.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add agent/operation_orchestration/executor.py tests/test_operation_executor.py
git commit -m "feat: execute operation dependency graphs"
```

### Task 7: Public orchestrator and acceptance flows

**Files:**
- Create: `agent/operation_orchestration/orchestrator.py`
- Create: `agent/operation_orchestration/__init__.py`
- Create: `tests/test_operation_orchestrator.py`

- [ ] **Step 1: Write failing facade and acceptance tests**

Test that `run()` passes the original query/tree into the generator and generated operations plus site/project IDs into the executor. Add deterministic end-to-end fakes for the required scenarios: single create, chained create, create then expression, modify existing, delete existing, and branch `A -> {B, C}`. Assert final tree shape, target/output IDs, statuses, and that only dependency-free operations use location.

```python
def test_orchestrator_forwards_generated_operations_to_executor():
    generator = RecordingGenerator([create_op("op_0")])
    executor = RecordingExecutor()
    result = OperationOrchestrator(generator=generator, executor=executor).run(
        "在BILL_INFO下创建ACCT_INFO", sample_tree(), site_id="s", project_id="p"
    )
    assert generator.request.query == "在BILL_INFO下创建ACCT_INFO"
    assert executor.request.site_id == "s"
    assert executor.request.project_id == "p"
    assert result.success
```

- [ ] **Step 2: Run facade tests and verify RED**

Run: `python -m pytest tests/test_operation_orchestrator.py -q`

Expected: orchestrator import fails.

- [ ] **Step 3: Implement facade and exports**

Implement `OperationOrchestrator.__init__(generator=None, locator=None, executor=None, action_adapter=None)` so defaults share the supplied/default locator and adapter consistently. `run()` constructs `GenerateOperationsRequest`, then `ExecuteOperationsRequest`, and returns the executor response. Export all public models, components, `build_node_index`, and `is_valid_candidate` from `__init__.py`.

- [ ] **Step 4: Run acceptance tests and verify GREEN**

Run: `python -m pytest tests/test_operation_orchestrator.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add agent/operation_orchestration/orchestrator.py agent/operation_orchestration/__init__.py tests/test_operation_orchestrator.py
git commit -m "feat: expose operation orchestrator"
```

### Task 8: Regression verification and documentation consistency

**Files:**
- Verify: all files above
- Modify only if verification exposes a defect in the new orchestration code or its tests.

- [ ] **Step 1: Run focused orchestration tests**

Run:

```powershell
python -m pytest tests/test_operation_models.py tests/test_operation_node_index.py tests/test_operation_generator.py tests/test_operation_locator.py tests/test_operation_action_adapter.py tests/test_operation_executor.py tests/test_operation_orchestrator.py tests/test_planner_prompt.py -q
```

Expected: all focused tests pass with no new warnings.

- [ ] **Step 2: Run existing node-operation regressions**

Run:

```powershell
python -m pytest tests/test_generate_node_operation.py tests/test_generate_node_operation_integration.py tests/test_modify_node_operation.py tests/test_modify_node_operation_integration.py tests/test_value_logic_generator.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run the full repository suite**

Run: `python -m pytest -q`

Expected: all existing 197 tests plus the new orchestration tests pass; the pre-existing Pydantic class-config deprecation warning may remain.

- [ ] **Step 4: Check formatting, JSON validity, and worktree scope**

Run:

```powershell
python -m json.tool prompt.json > $null
git diff --check
git status --short
```

Expected: JSON parsing and diff checks succeed; status contains only intended orchestration files if the per-task commits were intentionally skipped.

- [ ] **Step 5: Commit final verification fixes if any**

```powershell
git add agent/operation_orchestration agent/generate_node_operation.py prompt.json tests
git commit -m "test: verify operation orchestration flows"
```

Skip this commit when Step 4 shows a clean worktree.
