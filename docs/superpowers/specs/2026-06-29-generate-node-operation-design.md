# Generate Node Operation Design

## Goal

Add a `GenerateNodeOperation` that accepts a natural-language request describing one node, the JSONPath of its target parent, and the current EDSL tree. It generates a valid `TreeNodeTerm` and an applicable add patch. Failures return structured errors and never return a partial patch.

## Public Contract

`GenerateNodeOperationInput` contains:

- `query: str`
- `node_path: str`, interpreted as the target parent node's JSONPath
- `edsl_tree: dict[str, Any]`
- `debug: bool = False`

`GenerateNodeOperationOutput` contains the requested operation metadata, resolved paths, generated node, patch, routing result, validation errors, and failure reason. `operation_type` is always `generate_node`. On success, `generated_node` and `patch` are present. On failure, both are absent.

The operation exposes a synchronous `execute(input)` entry point. Optional LLM collaborators are injected into the operation constructor so unit tests and offline callers remain deterministic.

## Architecture

The implementation is split into focused collaborators in `agent/generate_node_operation.py`:

1. `PathResolver` normalizes and parses the parent JSONPath, resolves exactly one existing node, checks that it is a container, and derives both the JSONPath children path and JSON Pointer patch path.
2. `NodeTypeRouter` classifies the query into one of `simple_leaf`, `parent`, `parent_list`, `ab_pivot_table`, or `ab_two_level_table`. Local rules provide the deterministic baseline; an injected LLM route function may enhance the result.
3. `CommonFieldGenerator` produces only `xml_name_property`, `annotation`, and `reference_logic_area_id_list`. It never produces IDs, semi-structured metadata, prompts, or type-specific fields.
4. `TypeSpecificFieldGenerator` constructs only fields allowed for the routed type, reusing the node models in root `models.py`.
5. `NodeAssembler` merges the routed type, common fields, and type-specific fields into a draft.
6. `TreeNodeTerm.model_validate()` applies schema validation, defaults, AB discriminator repair, and illegal optional-field cleanup.
7. `NodePatchBuilder` serializes the validated node and builds an RFC 6902 add operation.

Each collaborator has one public responsibility and can be unit-tested independently.

## Path and Patch Semantics

`node_path` is a JSONPath identifying the parent. Paths without `$` are normalized by prefixing `$.`. The resolver rejects malformed paths, missing parents, ambiguous paths that match more than one node, non-dictionary targets, and targets whose `tree_node_type` cannot contain children.

Allowed containers are `parent` and `parent_list`. The mapping root is allowed when it resolves to one of these model types; there is no separate unvalidated root exception.

For a parent path such as `$.mapping_content`, the resolver returns:

- `parent_path`: `$.mapping_content`
- `children_path`: `$.mapping_content.children`
- patch path: `/mapping_content/children/-`

The patch is:

```json
{
  "op": "add",
  "path": "/mapping_content/children/-",
  "value": {}
}
```

The final `value` is the complete serialized `TreeNodeTerm`. JSONPath segments supported by the resolver are ordinary object fields and numeric list indexes, matching the project's existing path usage. Unsupported wildcard, filter, slice, or recursive-descent expressions fail as `INVALID_NODE_PATH` rather than producing an unsafe patch path.

## Routing and Field Generation

Local routing uses explicit term groups with precedence from the most structurally specific type to the least specific: two-level table, pivot table, list, parent, then simple leaf. This prevents a generic detail-record term from overriding a stronger two-level-table phrase. The route result records the chosen type, confidence, reason, evidence terms, and whether the source was local rules or LLM.

The common field generator extracts an explicit Latin identifier when present. Otherwise it maps recognized Chinese business tokens to stable uppercase identifiers and uses a deterministic normalized fallback. It rejects an empty result as `XML_NAME_EMPTY`. XML empty-field behavior defaults to `none` and changes to `half` or `full` only when explicitly requested. Logic-area references are populated only from explicit IDs in the query.

Type-specific defaults are:

- `simple_leaf`: `DataExpressionTerm`, `DataTypeTerm`, and `SupportBigCustAcctTerm`. Data type is `money`, `time`, or `simple_string` according to explicit query terms.
- `parent`: empty `children` and `local_context`.
- `parent_list`: `DataSourceTerm`, `SupportBigCustAcctTerm`, empty `children`, `local_context`, and `iter_local_context`.
- `ab_pivot_table`: `PivotTableTerm` as `ab_content`.
- `ab_two_level_table`: `TwoLevelTableTerm` as `ab_content`.

Expression, BO, naming-SQL, and AB-planning integrations remain adapters only. Existing generator, resource-manager, and planner internals are out of scope.

## LLM Boundary

Two prompt-manager entries are added:

- `node_type_route_prompt` returns only the route result JSON.
- `common_node_field_prompt` returns only the three common fields.

The operation does not require a live LLM. When an injected LLM collaborator is available, its response is parsed and constrained to the relevant Pydantic output model. Invalid responses fall back to deterministic local behavior. The LLM never creates IDs, type-specific defaults, a complete node, or a patch.

## Model Corrections

The root `models.py` remains the single source of node schemas. The implementation will make the file importable in this repository by replacing its unavailable external `common.utils.id_generator` dependency with a small project-local ID generator module while preserving the call contract.

`TreeNodeTerm.adjust_for_node_type` will include `iter_local_context` in the complete optional-field set. `special_configs` will use factories rather than shared lists or model instances, ensuring each validated node receives independent defaults. The existing `fill_ab_content_type` validator remains responsible for aligning the outer and inner AB types, with direct tests for both AB node kinds.

## Error Handling

Failures are converted into structured validation entries containing at least `code`, `message`, and optional path/context data. Supported codes include:

- `INVALID_NODE_PATH`
- `TARGET_PARENT_NOT_FOUND`
- `TARGET_PARENT_CANNOT_HAVE_CHILDREN`
- `NODE_TYPE_ROUTE_FAILED`
- `NODE_SCHEMA_VALIDATION_FAILED`
- `XML_NAME_EMPTY`
- `TYPE_SPECIFIC_FIELD_MISSING`

Pydantic validation details are preserved under `validation_errors`. No failure path invokes `NodePatchBuilder`, and the output explicitly has no generated node or patch.

## Testing

Unit tests cover each collaborator and all eight requested acceptance scenarios: simple leaf, parent, parent list, pivot table, two-level table, invalid leaf parent, illegal-field cleanup, and empty XML name. Additional tests verify malformed and missing paths, ambiguous/unsupported JSONPath constructs, independent defaults between nodes, AB inner/outer type alignment, invalid LLM-result fallback, and output failure invariants.

A minimal end-to-end test executes the operation against an EDSL tree, applies the returned RFC 6902 add patch with a small test helper, and validates the inserted value with `TreeNodeTerm.model_validate()`. The existing full test suite must remain green.

## Scope

This change adds node generation only. It does not mutate the input tree, decompose multi-node requests, refactor expression generation, redesign resource loading, or extend the existing planner.
