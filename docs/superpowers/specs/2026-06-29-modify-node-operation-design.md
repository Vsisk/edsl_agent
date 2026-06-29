# Modify Node Operation Design

## Goal

Add a `ModifyNodeOperation` that reads one existing node from the current EDSL tree, interprets a natural-language modification request, creates a structured modification plan, executes either field updates or a complete type migration, validates the result as a `TreeNodeTerm`, and returns an applicable RFC 6902 patch list. A failed operation never returns an applicable patch.

## Public Contract

`ModifyNodeOperationInput` contains:

- `query: str`
- `node_path: str`, interpreted as the target node's JSONPath
- `edsl_tree: dict[str, Any]`
- `site_id: str | None = None`
- `project_id: str | None = None`
- `debug: bool = False`
- `allow_destructive: bool = False`

`ModifyNodeOperationOutput` contains `success`, the constant operation type `modify_node`, the requested path, the original and modified nodes, a patch list, the routed intent, a migration report, validation errors, and a failure reason. Successful outputs always include `original_node`, `modified_node`, and at least one patch. Failed outputs preserve `original_node` when resolution succeeded but never include `modified_node` or patches.

The operation exposes synchronous `execute(input)`. Optional intent/plan LLM callables and expression, data-source, and AB-content adapters are constructor-injected so local tests remain deterministic.

## Architecture

The implementation lives in `agent/modify_node_operation.py` and is divided into focused units:

1. `NodeResolver` resolves the target node and derives its JSON Pointer, parent node, ancestor nodes, and visible local/iteration context.
2. `ModifyIntentRouter` classifies the request without creating node JSON or patches.
3. `ModifyPlanGenerator` converts the intent into common-field updates, type-field updates, adapter requests, or a migration request.
4. `MigrationPlanner` computes field preservation, target initialization, dropped fields, context policies, children policy, and destructive risk.
5. `DestructiveChangeGuard` compares the original and candidate changes and enforces both explicit query authorization and `allow_destructive=True`.
6. `ModifyExecutor` applies the plan to a deep copy, invokes adapters when needed, and performs migrations using the existing type-specific generator.
7. `TreeNodeTerm.model_validate()` supplies defaults, strips illegal optional fields, and checks the node schema.
8. `SemanticValidator` verifies target-specific data type, data source, expression, and AB invariants.
9. `ModifyPatchBuilder` builds an RFC 6902 replace patch for the complete node.

The existing generate operation remains the owner of node-type routing and type-specific defaults. Modify code imports and composes those classes rather than duplicating their rules.

## Path Resolution and Context

The existing `PathResolver` is extended with a public, container-neutral simple-path resolution method. Its current parent-container `resolve()` behavior remains unchanged and delegates to the neutral primitive. Supported syntax remains ordinary object properties and numeric list indexes; wildcard, filter, recursive, and slice expressions fail with `INVALID_NODE_PATH`.

`NodeResolver` uses this primitive to resolve exactly one dictionary target. It derives the target JSON Pointer for patching and walks the path prefixes to collect parent and ancestor dictionaries. Visible context is collected from ancestor and current `parent`/`parent_list` nodes, preserving source paths and distinguishing `local_context` from `iter_local_context`.

## Intent and Modification Plan

`ModifyIntent` supports:

- `set_common_field`
- `modify_expression`
- `modify_datatype`
- `modify_data_source`
- `modify_context`
- `modify_ab_content`
- `change_node_type`
- `mixed`

Local routing applies the most specific rule first: explicit node-type conversion, AB content, context, data source, expression, datatype, then common fields. When multiple independent categories are present, it returns `mixed` and lists every affected field. Optional LLM output is accepted only after Pydantic validation; invalid or unavailable LLM output falls back to local routing.

`NodeModifyPlan` contains only business updates and adapter queries. It never contains patches. Common updates are limited to `xml_name_property` members, `annotation`, and `reference_logic_area_id_list`. Type updates are limited to fields valid for the current node type. Unknown or structurally unsafe requested fields fail as `UNSUPPORTED_FIELD_UPDATE`.

The local plan generator extracts explicit values from requests such as XML names, annotations, XML format/empty-field modes, logic-area IDs, direct expressions, and datatype names/configuration. The optional `modify_plan_prompt` may improve extraction but is constrained by the same plan model and allowlists.

## Expression and Complex-Type Adapters

Expression modification does not reimplement expression generation. An `ExpressionModificationAdapter` receives the query, current node, parent node, ancestors, visible context, EDSL tree, and optional site/project IDs. The default adapter delegates to the existing `ValueLogicGenerator` when its required project context is available. Tests inject a deterministic fake adapter. Adapter failure becomes `EXPRESSION_GENERATION_FAILED`.

Data-source and AB-content modification use equivalent injected adapter boundaries. Without an adapter, simple type migrations still initialize valid model defaults, while an in-place request for complex data-source or AB content returns `UNSUPPORTED_FIELD_UPDATE`. No placeholder or guessed schema is emitted.

Datatype changes are local and deterministic. The generator selects `simple_string`, `time`, or `money`, preserves compatible explicit configuration, and applies only explicitly requested values such as precision, currency, or time format. The result must validate as `DataTypeTerm`; otherwise it fails with `DATATYPE_VALIDATION_FAILED`.

## Type Migration

All type changes use a `NodeTypeMigrationPlan`; replacing only `tree_node_type` is prohibited. The migration always preserves these base fields:

- `node_id`
- `xml_name_property`
- `annotation`
- `edsl_semi_struct`
- `edsl_prompt`
- `reference_logic_area_id_list`

The current node ID is retained unless the query explicitly requests rebuilding the node. Rebuild requests call `update_id()` after successful migration planning.

Target-specific fields are initialized by the generate operation's `TypeSpecificFieldGenerator`. Migration policies are:

- `parent -> parent_list`: keep children and local context; initialize data source, big-account support, and iteration context.
- `parent_list -> parent`: keep children and local context; drop data source, big-account support, and iteration context.
- `simple_leaf -> parent`: drop leaf fields; initialize empty children and local context.
- `simple_leaf -> parent_list`: drop leaf fields; initialize all list fields.
- `parent` or `parent_list -> simple_leaf`: reject when children exist unless destructive authorization is satisfied; then drop container fields and initialize leaf fields.
- `simple_leaf -> ab_pivot_table` or `ab_two_level_table`: drop leaf fields and initialize matching AB content.
- `ab_pivot_table <-> ab_two_level_table`: preserve compatible `data_source` and `group_by_fields`, replace the remaining AB content with the target model.
- `ab_* -> parent`, `simple_leaf`, or `parent_list`: drop AB content and mark the migration destructive.

After migration, `TreeNodeTerm.model_validate()` performs the authoritative allowed-field cleanup. The serialized AB payload explicitly includes an inner `tree_node_type` equal to the outer type.

## Destructive Change Guard

Destructive changes include dropping non-empty children, local context, iteration context, data source, AB content, or overwriting a non-empty expression/data source. Container-to-leaf and AB-to-non-AB migrations are destructive even if the corresponding structure is currently empty.

A destructive change is allowed only when both conditions hold:

1. `allow_destructive` is true.
2. The query explicitly contains authorization such as delete, clear, discard, overwrite, rebuild, or their Chinese equivalents.

Otherwise the operation fails with `DESTRUCTIVE_CHANGE_NOT_ALLOWED`. An allowed destructive result includes a migration report listing dropped fields, prior child count, children action, preserved fields, and initialized fields.

## Validation and Patch Semantics

Every candidate is validated as a complete `TreeNodeTerm`. `SemanticValidator` then enforces:

- expression fields only on `simple_leaf`
- supported datatype values and valid datatype configuration
- data source only on `parent_list`
- AB content only on AB nodes
- inner and outer AB types match

All successful modifications use one whole-node RFC 6902 replace patch:

```json
{
  "op": "replace",
  "path": "/mapping_content/children/0",
  "value": {}
}
```

Using a whole-node replacement for local edits and migrations keeps behavior uniform and prevents stale fields from surviving a type change. The input tree is never mutated.

## Errors

Structured failures use at least these codes:

- `INVALID_NODE_PATH`
- `TARGET_NODE_NOT_FOUND`
- `MODIFY_INTENT_ROUTE_FAILED`
- `UNSUPPORTED_FIELD_UPDATE`
- `UNSUPPORTED_TYPE_MIGRATION`
- `DESTRUCTIVE_CHANGE_NOT_ALLOWED`
- `NODE_SCHEMA_VALIDATION_FAILED`
- `EXPRESSION_GENERATION_FAILED`
- `DATATYPE_VALIDATION_FAILED`
- `DATA_SOURCE_VALIDATION_FAILED`
- `AB_CONTENT_VALIDATION_FAILED`

Pydantic details are retained in `validation_errors`. Patch building occurs only after all schema, semantic, and destructive checks pass.

## Prompts

Two prompt-manager entries are added:

- `modify_intent_route_prompt` emits only `ModifyIntent` JSON.
- `modify_plan_prompt` emits only `NodeModifyPlan` JSON.

Neither prompt may emit a complete node or patch. LLM fields outside the corresponding Pydantic contract are ignored, while invalid required values cause deterministic local fallback.

## Testing

Unit tests cover node resolution/context, every intent class, plan allowlists, all migration policies, destructive-guard decisions, schema/semantic failures, adapter failure mapping, prompt rendering, and patch generation.

Acceptance tests cover:

- XML name and annotation updates
- simple-leaf expression modification through an injected adapter
- simple-leaf money datatype modification
- parent to parent-list migration while preserving children
- authorized parent-list to parent migration while dropping data source and iteration context
- simple-leaf to parent
- simple-leaf to pivot table
- pivot table to two-level table
- rejected container-to-leaf migration with children
- authorized container-to-leaf migration with a migration report
- valid `TreeNodeTerm` deserialization after every successful modification
- allowed-field cleanup after every type change
- failure outputs with no patches

A minimal end-to-end test applies the returned replace patch to a copied EDSL tree and validates the replaced node. The complete existing suite, including GenerateNode tests, must remain green.

## Scope

This change modifies one node per operation. It does not split multi-node queries, mutate the input tree, redesign expression generation, or refactor resource management and planning internals. Advanced in-place data-source and AB-content editing remains adapter-gated rather than generating speculative structures.
