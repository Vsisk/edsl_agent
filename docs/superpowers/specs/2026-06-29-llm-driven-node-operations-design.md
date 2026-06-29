# LLM-Driven Node Operations Design

## Goal

Replace production keyword and regular-expression interpretation in `GenerateNodeOperation` and `ModifyNodeOperation` with narrow, validated LLM calls. Keep schema construction, path handling, migration policy, destructive enforcement, model validation, and patch construction deterministic and local.

## Decision

Use multiple responsibility-specific LLM calls rather than one call that emits a complete node or patch. Every LLM response is validated through a Pydantic contract before local code consumes it. If an LLM call raises, is unavailable, returns malformed JSON, or violates its output contract, the operation fails with a structured error. There is no production keyword fallback and no retry.

Constructor injection remains available so tests can supply deterministic fake LLM callables. Without an injected callable, the operations call the existing `generate_by_llm()` entry point and prompt manager.

## Generate Node Flow

Generation uses three semantic calls:

1. `NodeTypeRouter` renders `node_type_route_prompt` and validates `NodeRouteResult`.
2. `CommonFieldGenerator` renders `common_node_field_prompt` and validates `CommonNodeFields`.
3. `NodeContentIntentGenerator` renders `node_content_intent_prompt` and validates `NodeContentIntent`.

`NodeContentIntent` contains only decisions needed by the local type-specific generator:

- routed `tree_node_type`
- leaf datatype: `simple_string`, `time`, or `money`
- whether explicit expression generation is required
- whether explicit data-source generation is required
- expression/data-source/AB adapter query text
- reason and evidence

`TypeSpecificFieldGenerator` consumes the routed type and structured content intent. It no longer searches query text. It still creates model defaults locally and delegates expression, data-source, or AB content work through existing adapters only when the intent requests it.

The production constants and branches used for keyword interpretation are removed, including node-type term tables, Chinese-to-XML-name term maps, money/time term lists, and XML-label/logic-area query extraction. The LLM common-field response supplies those values directly.

Generation failures map to:

- `NODE_TYPE_ROUTE_FAILED`
- `COMMON_FIELD_GENERATION_FAILED`
- `NODE_CONTENT_INTENT_FAILED`
- existing adapter/schema errors after semantic routing succeeds

No failed generation returns a node or patch.

## Modify Node Flow

Modification uses two semantic calls:

1. `ModifyIntentRouter` renders `modify_intent_route_prompt` using the query and current-node JSON, then validates `ModifyIntent`.
2. `ModifyPlanGenerator` renders `modify_plan_prompt` using the query, current-node JSON, and validated intent JSON, then validates `NodeModifyPlan`.

The plan becomes the only source of query-derived field values. It supplies:

- common-field updates
- allowlisted type-field updates
- expression, data-source, and AB-content adapter queries
- datatype configuration updates
- an optional target type
- `destructive_authorized`, indicating that the user explicitly requested deletion, clearing, replacement, or rebuilding

`ModifyExecutor` applies only structured plan values. It no longer parses datatype words, precision, XML names, annotations, labels, or logic-area IDs from the original query. `ModifyIntentRouter` and `ModifyPlanGenerator` no longer contain category keyword tables or extraction regular expressions.

`MigrationPlanner` remains deterministic. It computes field preservation and removal from source and target types, not from query wording. `DestructiveChangeGuard` requires both `allow_destructive=True` and `plan.destructive_authorized=True`; it no longer scans query text. Node rebuild uses a structured plan flag rather than searching for “rebuild” terms.

Modification failures map to:

- `MODIFY_INTENT_ROUTE_FAILED`
- `MODIFY_PLAN_GENERATION_FAILED`
- existing adapter, destructive, semantic, and schema errors after plan validation succeeds

No failed modification returns patches.

## LLM Gateway

Each router/generator accepts an optional callable with the same semantic inputs used by its prompt. The default callable is a small adapter over `generate_by_llm(prompt_key, query=..., ...)`. This keeps operation orchestration independent of HTTP/client details and makes unit tests deterministic.

The gateway does not catch and reinterpret external failures. Each semantic component catches its gateway exception once and raises its own `OperationFailure` code with the original exception chained for diagnostics. Validation failures use the same component-specific code.

The existing low-level `LLMClient`, resource manager, expression generator, and planner are not redesigned.

## Prompt Contracts

Prompts remain strict JSON-only and include explicit allowlists.

`node_type_route_prompt` outputs only the five supported generated node types, confidence, reason, and evidence.

`common_node_field_prompt` outputs only:

- `xml_name_property.xml_name`
- `xml_name_property.xml_format_type`
- `xml_name_property.xml_empty_field_type`
- `annotation`
- `reference_logic_area_id_list`

`node_content_intent_prompt` outputs datatype and adapter-generation intent. It cannot emit IDs, complete type-specific model objects, a final node, or a patch.

`modify_intent_route_prompt` outputs only `ModifyIntent`, including target type and affected fields.

`modify_plan_prompt` outputs only `NodeModifyPlan`, including `destructive_authorized` and structured field updates. It cannot output a final node or patch.

Every prompt explains that `node_id`, `edsl_semi_struct`, and `edsl_prompt` are local/model-owned.

## Local Validation and Safety

The following remain entirely local:

- JSONPath resolution and JSON Pointer construction
- target-parent/container checks
- allowed fields per node type
- type-specific default model construction
- node ID creation and optional rebuild
- type migration matrix
- destructive-risk calculation
- requirement for the external `allow_destructive` switch
- `TreeNodeTerm.model_validate()`
- AB inner/outer discriminator alignment
- RFC 6902 patch construction

LLM output never bypasses an allowlist or Pydantic validation. Extra fields are ignored or rejected according to the boundary model, and invalid required fields fail the operation.

## Tests

Production behavior tests inject deterministic fake semantic callables instead of relying on keyword behavior or network access. Test fixtures provide valid route, common-field, content-intent, modify-intent, and modify-plan responses for each acceptance scenario.

Additional tests verify:

- default components call `generate_by_llm()` with the correct prompt key and variables
- each LLM response contract accepts valid JSON
- malformed payloads and invalid enum values return component-specific errors
- gateway exceptions return component-specific errors
- no keyword fallback occurs after any LLM failure
- type-specific generation consumes structured content intent
- modify execution consumes structured plan datatype/common values without reading query words
- destructive authorization comes only from the validated plan and still requires `allow_destructive=True`
- all GenerateNode and ModifyNode success, migration, AB, and patch behaviors remain valid
- the complete repository test suite remains green

## Scope

This change replaces semantic query interpretation inside the two node operations. It does not remove keyword search from the resource-search subsystem, because that subsystem performs explicit resource lookup rather than node intent classification. It does not change expression-generation internals, resource ranking, the LLM transport, or the EDSL node schemas.
