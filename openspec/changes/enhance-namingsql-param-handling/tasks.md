## 1. Regression Coverage

- [x] 1.1 Add tests for SQL-derived `is_list` inference covering `=`, `<>`, `>`, `>=`, `<`, `<=`, `${in,:PARAM}`, and `${not_in,:PARAM}`.
- [x] 1.2 Add tests showing SQL-derived cardinality overrides conflicting NamingSQL metadata and writes log diagnostics.
- [x] 1.3 Add tests for binding params to BO fields from SQL left-side fields, including `CATEGORY ${in,:CHARGE_TYPE}` where param and field names differ.
- [x] 1.4 Add tests showing ambiguous or unsupported SQL usage leaves `linked_field_name` absent instead of guessing.
- [x] 1.5 Add NamingSQL profile loader tests showing `SELECT /*+ INDEX ... */ BE_ID, ...` extracts real fields and excludes hint fragments from `return_fields`.
- [x] 1.6 Add Expression Spec tests for literal value resolution from `query + field context description + is_list`, including single value, one-element list, and multi-code list outputs.
- [x] 1.7 Add Expression Spec tests for `PARAM_CARDINALITY_MISMATCH` on literal and resource-backed scalar/list conflicts.
- [x] 1.8 Add Expression Spec tests showing resources with unknown cardinality are not guessed into final bindings and leave the parameter unbound/empty with a log message.
- [x] 1.9 Add planner boundary tests proving Planner receives resolved NamingSQL parameter values but no BO field description or field context metadata.

## 2. NamingSQL Profile Field Parsing

- [x] 2.1 Locate `NamingSqlProfileLoader` return field extraction and preserve existing no-hint behavior.
- [x] 2.2 Strip optimizer hint comments beginning with `/*+` before parsing SELECT return fields.
- [x] 2.3 Ensure the actual projected field after the hint, such as `BE_ID`, is still included in `return_fields`.
- [x] 2.4 Confirm hint tokens such as `INDEX`, index names, and comment delimiters never enter `return_fields`.

## 3. Resource Search Parameter Enrichment

- [x] 3.1 Locate the existing NamingSQL search result construction path in `ResourceSearchService` or the current equivalent resource search module.
- [x] 3.2 Implement small deterministic SQL parameter usage parsing inside existing NamingSQL profile/search utilities for supported scalar comparison and template list patterns.
- [x] 3.3 Produce an effective `param_name -> field_name, is_list` map from SQL command usage without calling the LLM.
- [x] 3.4 Enrich selected NamingSQL params with SQL-derived `is_list`, reusing the existing `ParamTerm.is_list` field where possible.
- [x] 3.5 Bind each param to the BO field found from the SQL left-side field and reuse `linked_field_name` for the field name and attach only description through temporary field context.
- [x] 3.6 Preserve existing behavior when SQL command is missing, unsupported, or ambiguous, except for adding diagnostics.

## 4. Expression Spec Parameter Binding

- [x] 4.1 Thread enriched NamingSQL params into the existing Expression Spec generation input without changing the main generation flow.
- [x] 4.2 Update the NamingSQL parameter binding prompt/context so it can use field context descriptions while treating it as untrusted reference data.
- [x] 4.3 Normalize resolved literal values according to `param.is_list`: scalar for single params and list for list params.
- [x] 4.4 Keep field context descriptions, value semantics, and evidence out of the final ExpressionContextSpec.

## 5. Cardinality Validation

- [x] 5.1 Add a focused validator for final NamingSQL param bindings that checks effective `data_type` and `is_list`.
- [x] 5.2 Validate literal bindings so single params reject multiple values and list params emit list-shaped values.
- [x] 5.3 Validate resource-backed bindings against known context/local/resource return types and return `PARAM_CARDINALITY_MISMATCH` on scalar/list mismatch.
- [x] 5.4 Leave resource-backed bindings with unknown cardinality unbound/empty through existing fallback behavior and log the reason.
- [x] 5.5 Ensure validation happens before Planner invocation and Planner is not used to repair cardinality errors.

## 6. Diagnostics And Boundary Cleanup

- [x] 6.1 Add debug/warning logs for `param_name`, SQL-bound field, effective `is_list`, `linked_field_name`, metadata conflicts, unknown resource cardinality, and final param value.
- [x] 6.2 Use the project's existing logging mechanism and avoid adding new diagnostic metadata models.
- [x] 6.3 Audit Planner-facing resource summaries and final Spec serialization to confirm BO field descriptions are not leaked.

## 7. Verification

- [x] 7.1 Run the focused NamingSQL profile loader tests covering return field parsing and optimizer hints.
- [x] 7.2 Run the focused resource search/spec orchestration tests covering NamingSQL selection and parameter metadata.
- [x] 7.3 Run the focused expression spec/generation tests covering parameter binding and cardinality validation.
- [x] 7.4 Run the focused planner tests covering NamingSQL parameter boundary behavior.
- [x] 7.5 Run `openspec status --change "enhance-namingsql-param-handling"` and confirm the change is apply-ready.

