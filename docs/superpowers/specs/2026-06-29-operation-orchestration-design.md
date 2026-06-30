# Operation Orchestration Design

## Goal

Add an operation-orchestration layer that decomposes one natural-language query into single-node operations, locates initial targets, executes operations in dependency order, and threads newly created node IDs into downstream operations. Existing node generation, node modification, and expression generation remain unchanged behind an adapter. Node deletion is added as a minimal deterministic local operation and exposed only through that adapter.

## Package Structure

Create a focused `agent/operation_orchestration/` package:

- `models.py`: `Operation` and all generator, locator, executor request/response models.
- `node_index.py`: DFS traversal, candidate summaries, node-ID-to-JSONPath indexing, and intent-specific candidate filtering.
- `generator.py`: LLM-backed operation decomposition, dependency construction, validation, and container-intent query enrichment.
- `locator.py`: LLM-backed selection from locally generated candidates for dependency-free operations only.
- `action_adapter.py`: adapters over existing generate, modify, and expression capabilities plus deterministic local deletion.
- `executor.py`: graph validation, stable topological execution, dependent-target resolution, index rebuilding, and fail-fast behavior.
- `orchestrator.py`: the public `run()` entry point.
- `__init__.py`: explicit public exports.

Add two strict JSON prompts to `prompt.json`:

- `operation_generator_prompt` for decomposition and dependencies.
- `operation_locator_prompt` for selecting a node from supplied DFS candidates.

## Operation Model

`Operation` follows the requested contract: `op_id`, `query`, `intent_type`, `depends_on`, `target_from`, located target fields, output node ID, status, and error message. Mutable list defaults use Pydantic factories.

Every operation affects exactly one node. IDs are stable and sequential (`op_0`, `op_1`, ...). The orchestration layer rejects duplicate IDs, references to missing operations, self-dependencies, cycles, an invalid `target_from`, and multiple dependencies without `target_from`.

## Generation

`OperationGenerator` sends the user query and a lightweight tree summary to `operation_generator_prompt`. It validates the strict response through Pydantic and then performs deterministic graph validation. The LLM produces intent and dependency semantics but never produces a final JSONPath or target node ID.

Generation has a deterministic second pass for branch/container intent. If a newly created node is the target source for one or more downstream create operations, its operation query is enriched to state that the new node must be capable of containing child nodes. For example:

```text
新增可包含子节点的 A 节点
在 A 节点下新增 B 节点
在 A 节点下新增 C 节点
```

The B and C operations both depend directly on A; no artificial B-to-C dependency is added. The enriched A query allows the existing node-generation router to select `parent`, `parent_list`, or an AB table type rather than `simple_leaf`. The orchestration layer does not hard-code which container type to choose.

## Node Index and Location

`build_node_index()` walks dictionaries and lists using DFS. Each node-like dictionary with a non-empty `node_id` becomes a `NodeLocateCandidate` containing its exact local JSONPath, node type, XML name, annotation, parent metadata, and child count. Duplicate node IDs are rejected because dependent lookup would otherwise be ambiguous.

AB fields are also indexed even though they do not live in `children`. Dictionaries in the known AB field slots use `field_id` as their canonical candidate ID and record that the identity came from `field_id`, together with the containing AB slot. Common AB fields and two-level summary fields receive distinct synthetic candidate types. Duplicate values across `node_id` and `field_id` are rejected. Consequently an AB create operation may return `output_node_id=<field_id>`, and later operations resolve that ID to its real nested JSONPath through the same index.

The locator only accepts operations with no dependencies. It filters candidates locally by intent before invoking the LLM. Create operations accept `parent`, `parent_list`, `ab_single_mapping_table`, `ab_two_level_table`, and `ab_pivot_table`; the other intents accept existing node candidates.

`operation_locator_prompt` receives only the operation query, intent type, and candidate summaries. Its strict response includes `selected_node_id`, `selected_jsonpath`, `confidence`, and `reason`. Local code verifies that the ID exists and that the returned path exactly matches the same candidate. The LLM cannot introduce a path.

If LLM location fails for `create_node`, the locator falls back to the first root-level indexed node that is a valid create parent. It fills the real node ID and JSONPath and marks the operation located. If no valid root container exists, location fails. Modify, expression, and delete operations never use root fallback.

## Action Adapter

`OperationActionAdapter` is the executor's only dependency on node actions.

- Create calls the existing `GenerateNodeOperation`, verifies success, applies its RFC 6902 add patch to a deep copy of the current tree, and returns `created_node_id` plus the updated tree. Existing path validation is minimally extended so all create-parent types required by orchestration are accepted.
- Modify calls the existing `ModifyNodeOperation`, verifies success, applies its replace patch list, and returns the updated tree.
- Expression generation calls the existing `ValueLogicGenerator`, converts its expression result into the existing `DataExpressionTerm` shape, replaces the target node's `data_expression`, and returns the updated tree. Optional site/project IDs are normalized for the existing request boundary.
- Delete resolves the already-located target deterministically, rejects deleting a root/no-parent target, removes exactly one list child from a deep copy, and returns its parent node ID plus the updated tree. It performs no semantic search and contains no LLM logic.

Patch application helpers support only the add/replace operations emitted by the existing modules and fail on malformed or unsupported patches.

### AB Field Creation Branch

When the located create parent is an AB table, `GenerateNodeOperation` handles the field as an internal atomic branch instead of appending a `TreeNodeTerm` to `children`. A narrow placement decision selects among the slots that are valid for the concrete AB type:

- `ab_single_mapping_table`: `detail_fields` only; ambiguous placement defaults there.
- `ab_two_level_table`: `group_by_fields`, `group_region.group_related_fields`, `group_region.summary_fields`, or `detail_region.detail_fields`; ambiguous placement defaults to `group_region.group_related_fields`.
- `ab_pivot_table`: `group_by_fields`, `group_region.group_related_fields`, or `group_region.sum_fields`; ambiguous placement defaults to `group_region.group_related_fields`.

The branch reuses the existing narrow common-field generation contract and validates the resulting field and complete AB parent with the existing Pydantic models. It returns the created field's `field_id` as `created_node_id`.

Creating a two-level `summary_fields` item is one internal atomic branch closure. The operation creates a same-name `CommonFieldTerm` in `detail_region.detail_fields`, creates the requested `SummaryField` in `group_region.summary_fields`, and sets the summary's `related_detail_field_name` to that shared XML field name. The replace patch is emitted only after the complete AB node validates, so failure cannot leave only one half. The external operation still returns the summary field's `field_id` as `output_node_id`.

Expression write-back is capability-aware: ordinary `simple_leaf` nodes store `data_expression` directly, while AB common fields store it through their `data_source` expression branch. Summary fields and container nodes reject expression generation. Modify calls forward optional site/project IDs. Delete continues to remove the exact located list element and returns the containing AB table's node ID when deleting an AB field.

## Execution

Before mutation, `OperationExecutor` validates the complete graph and computes a stable topological order that preserves input order among ready operations.

For each operation:

1. A dependency-free operation is located through `OperationLocator` unless it already has a valid located target.
2. A dependent operation never calls the locator. With one dependency it uses that upstream operation; with multiple dependencies it uses `target_from`.
3. The upstream `output_node_id` is resolved against a freshly built index of the current tree, producing the current JSONPath.
4. The adapter executes the corresponding action and returns a new tree.
5. The executor immediately rebuilds the node index.
6. It fills `output_node_id`: created node for create, target node for modify/expression, and parent node for delete.
7. It marks the operation `executed` and continues.

An operation may be marked `located` only when both target fields are populated and agree with the current index. Every successful operation must have a non-empty output node ID.

## Failure Semantics

Graph validation failures occur before execution and leave the input tree unchanged. Runtime execution is fail-fast and non-transactional:

- the first failing operation is marked `failed` with its error message;
- execution stops immediately;
- operations not yet visited remain `pending`;
- the response returns the partial tree containing all prior successful updates;
- successful operations remain `executed` with their output IDs;
- no rollback is attempted because existing node operations are patch-based and provide no transaction boundary.

Locator failures include the candidate summaries for diagnosis. Dependent-target failures explicitly identify the missing upstream result or node ID.

## Public Flow

`OperationOrchestrator.run(query, target_tree, site_id=None, project_id=None)` calls the generator and then the executor. The returned `ExecuteOperationsResponse` contains success, the final or partial tree, every operation with its final status, and an optional top-level error message.

## Testing

Tests are split by responsibility and developed test-first:

- model defaults and graph validation: duplicate IDs, missing dependencies, invalid `target_from`, and cycles;
- DFS indexes: JSONPaths, parent summaries, AB containers, duplicate/missing IDs;
- generator: single operation, chained creation, expression dependency, branch dependency, container-query enrichment, and multiple dependencies;
- locator: filtering, valid selection, invented/mismatched selections, create root fallback, and no fallback for other intents;
- adapter: applying existing create and modify patches, expression write-back, deterministic deletion, and error propagation;
- executor: stable topology, upstream target resolution, index rebuild after every mutation, output-ID rules, and fail-fast partial results;
- orchestrator acceptance: single create, chained create, create then expression, existing-node modification, deletion, and `A -> {B, C}` branch creation;
- full repository regression suite.

LLM-dependent tests inject deterministic callables. Production prompts and default gateways receive focused contract tests without requiring network access.

## Scope Boundaries

This change does not rewrite node generation, node modification, expression planning, resource selection, or their LLM internals. It does not allow dependent operations to repeat semantic location, allow an LLM to invent JSONPaths, combine multiple node changes in one operation, add rollback, or generalize patch handling beyond what the existing actions require.
