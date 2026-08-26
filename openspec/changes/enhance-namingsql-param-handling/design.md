## Context

The current Expression Spec generation path selects resources before planning, then passes selected NamingSQL definitions and parameter bindings toward expression planning. `ParamTerm` already has `is_list` and `linked_field_name`, and earlier loader work can link same-name NamingSQL params to BO field types. That is not enough for this change because SQL usage can override metadata cardinality, and parameter names can differ from the BO field used in the SQL condition.

There is also a related NamingSQL profile parsing defect: SQL statements such as `SELECT /*+ INDEX ... */ BE_ID, ... FROM ...` can leak optimizer hint text into `return_fields`. Since profile return fields are used for NamingSQL selection, hint comments must be removed before parsing the SELECT field list.

The intended architecture remains:

`SearchRequestGenerator -> ResourceSearchService -> ExpressionSpecGenerator -> Planner`

In the current codebase, implementation may live under the equivalent resource search/spec orchestration/expression generation modules, but the responsibility boundary must stay the same: resource search enriches NamingSQL parameter contracts, Expression Spec resolves and validates final values, and Planner only consumes completed bindings.

## Goals / Non-Goals

**Goals:**

- Infer NamingSQL parameter `is_list` from SQL command usage with deterministic code.
- Bind each NamingSQL parameter to its SQL left-side BO field when this can be determined reliably, including non-identical param/field names such as `CATEGORY ${in,:CHARGE_TYPE}`.
- Attach only `field_name` and `description` as temporary field context between resource search and Expression Spec generation.
- Resolve final literal/resource parameter values in Expression Spec generation using query semantics, optional BO field description, and `is_list`.
- Reject literal or resource bindings whose scalar/list cardinality conflicts with the NamingSQL parameter contract.
- Exclude SELECT optimizer hints from NamingSQL profile return field parsing.
- Keep Planner free of NamingSQL business-code interpretation and param cardinality inference.

**Non-Goals:**

- Do not change the main generation flow or add a separate workflow.
- Do not introduce `NamingSqlParamResolver`, `EnumResolver`, `FieldSemanticResolver`, or equivalent standalone resolver modules.
- Do not structure field descriptions into enum models, value semantics, evidence models, or persisted semantic metadata.
- Do not persist field context descriptions into final ExpressionContextSpec or Planner input.
- Do not attempt broad SQL parsing beyond the required comparison and template `in`/`not_in` patterns in this lightweight change.

## Decisions

### Decision 1: Enrich params at resource search time

`ResourceSearchService` or the equivalent NamingSQL search path will enrich selected NamingSQL definitions before returning candidates. For every NamingSQL param, it will produce an effective param definition containing existing type fields, SQL-derived `is_list`, and temporary field context.

Alternative considered: enrich params inside Planner. Rejected because Planner should consume a finished resource contract, not infer SQL semantics or business-code mappings.

### Decision 2: SQL command is authoritative for cardinality

The implementation will parse `sql_command` for supported parameter usages:

- `FIELD = :PARAM`, `FIELD <> :PARAM`, `FIELD > :PARAM`, `FIELD >= :PARAM`, `FIELD < :PARAM`, `FIELD <= :PARAM` => `is_list=false`
- `FIELD ${in,:PARAM}` and `FIELD ${not_in,:PARAM}` => `is_list=true`

When metadata is missing or matches SQL, the effective value is straightforward. When metadata conflicts with SQL, SQL wins and the system records debug/warning information.

Alternative considered: trust existing metadata when present. Rejected because the user's requirement explicitly treats SQL command usage as the source of truth for single/list shape.

### Decision 3: Field binding comes from SQL left-side field, not param name

The same SQL parse pass will record `param_name -> field_name` from the left side of supported conditions. The BO registry for the NamingSQL's BO will be searched for that field, preferably by exact/normalized field name. If the field is found, attach:

```json
{"field_name": "CATEGORY", "description": "..."}
```

If parsing is ambiguous or the field is not found, `linked_field_name` remains absent/`None` and no field context is attached.

Alternative considered: rely on `param_name == field_name` or existing `linked_field_name`. That preserves old behavior but misses `CATEGORY ${in,:CHARGE_TYPE}`, which is a required scenario.

### Decision 4: Reuse `linked_field_name` and keep field context transient

The enriched parameter definition reuses `linked_field_name` for the BO field name. The BO field description is carried only in a temporary field context for Expression Spec generation. Final ExpressionContextSpec stores only the resolved parameter value; persisted planner-facing structures must not include BO field descriptions.

Alternative considered: add value semantics/evidence to final Spec. Rejected to keep this change lightweight and avoid making Planner responsible for business semantic interpretation.

### Decision 5: Expression Spec validates final cardinality

Expression Spec generation will enforce `param.is_list` after resolving literal or resource values:

- list params must produce list-shaped values, including wrapping a single matched literal as `["C01"]`;
- single params must produce scalar values;
- multiple literal values for a single param, or resource return type mismatch, fail with `PARAM_CARDINALITY_MISMATCH`.
- resource bindings whose return cardinality is unknown must not be forced into the final binding; leave the parameter unbound/empty through the existing fallback behavior and log the reason.

Alternative considered: allow Planner to repair mismatches. Rejected because Planner should not change the NamingSQL contract or reinterpret parameter semantics.

### Decision 6: Diagnostics use existing logging

Parameter enrichment and final binding diagnostics will be emitted through the project's existing logging mechanism. Tests can assert behavior directly from outputs and errors; they do not need a new diagnostic metadata model.

Alternative considered: add test-visible diagnostic fields to search results or specs. Rejected because diagnostics are operational support data and should not expand the planner-facing contract.

### Decision 7: Strip optimizer hints before profile return field extraction

`NamingSqlProfileLoader` will remove SELECT optimizer hint comments of the form `/*+ ... */` before extracting `return_fields`. The cleanup is scoped to hint/comment removal ahead of field-list extraction and must preserve the actual projected fields that follow the hint, for example `BE_ID` in `SELECT /*+ INDEX ... */ BE_ID, ACCT_ID FROM ...`.

Alternative considered: special-case tokens containing `INDEX` after field splitting. Rejected because the problem is SQL comment syntax, and removing optimizer hints before field parsing is simpler and avoids polluting aliases or first-field parsing.

## Risks / Trade-offs

- Regex-level SQL parsing may miss complex SQL conditions -> Limit this change to explicitly supported comparison and template `in`/`not_in` patterns, leave `linked_field_name=None` when unsure, and cover all supported patterns with tests.
- Metadata and SQL cardinality can conflict -> Prefer SQL, log the conflict, and keep the effective param contract deterministic.
- BO field descriptions can be noisy or ambiguous -> Use descriptions only as temporary context for resolving explicit business values; do not persist inferred explanation/evidence.
- Resource cardinality may not always be known -> Validate when return type metadata is available; for unknown resource cardinality, leave the parameter unbound/empty through existing fallback behavior and log the reason.
- Prompt size could grow if descriptions are long -> Pass only descriptions for bound fields on selected NamingSQL params, not whole BO field lists.
- SQL comment stripping could accidentally remove non-hint content -> Scope this fix to optimizer hint comments beginning with `/*+` and add regression tests for `SELECT /*+ INDEX ... */ BE_ID, ...`.

## Migration Plan

1. Add focused tests for SQL-derived cardinality, param-to-field binding, and SELECT optimizer hint return-field parsing.
2. Fix `NamingSqlProfileLoader` return field extraction so optimizer hints are stripped before parsing projected fields.
3. Extend existing NamingSQL profile/search utilities with small deterministic functions to parse supported SQL parameter usages and enrich effective NamingSQL params; do not add a standalone parser/resolver module.
4. Reuse the existing `ParamTerm.is_list` field and reuse `linked_field_name` for field identity and carry descriptions only in temporary field context.
5. Thread enriched params into Expression Spec generation without changing the main service flow.
6. Extend Expression Spec value binding to use field context descriptions and enforce literal/resource cardinality.
7. Add debug/warning logs for param name, SQL field, effective `is_list`, bound field, unknown resource cardinality, and final value.
8. Run the related resource loader/search, spec orchestration, expression generation, and planner boundary tests.

Rollback is limited: stop applying SQL-derived enrichment and the flow returns to current metadata-driven behavior.

## Open Questions

No open questions remain for the current lightweight scope. `${not_in,:PARAM}` is included in the first implementation, unknown-cardinality resource bindings remain unbound/empty instead of being guessed, and diagnostics use the existing logging path.

