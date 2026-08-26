## Why

NamingSQL parameter binding currently lacks enough deterministic contract information for downstream expression generation. Business values such as "一次性费用" may only be recoverable from the corresponding BO field description, and parameter cardinality must be derived from the SQL command instead of left to the Planner or LLM inference.

## What Changes

- Enrich selected NamingSQL parameter definitions inside the existing `ResourceSearchService -> ExpressionSpecGenerator` handoff with:
  - deterministic `is_list` inferred from SQL parameter usage;
  - temporary field context containing only `field_name` and `description` when the SQL condition can be reliably linked to a BO field.
- Add deterministic SQL parameter parsing for ordinary scalar comparisons and template-style list conditions such as `${in,:PARAM}` and `${not_in,:PARAM}`.
- Fix NamingSQL profile return field parsing so SELECT optimizer hints such as `/*+ INDEX ... */` are ignored instead of being parsed into the returned field list.
- Make `ExpressionSpecGenerator` use `query + field context description + param.is_list` when resolving final NamingSQL parameter values.
- Enforce cardinality for both literal and resource-backed parameter bindings before the final ExpressionContextSpec reaches the Planner.
- Keep the existing `SearchRequestGenerator -> ResourceSearchService -> ExpressionSpecGenerator -> Planner` flow unchanged.
- Keep field context descriptions out of the final ExpressionContextSpec and out of Planner responsibilities.

## Capabilities

### New Capabilities

- `namingsql-param-handling`: Defines deterministic NamingSQL parameter cardinality inference, lightweight BO field description binding, and Expression Spec parameter value validation.

### Modified Capabilities

## Impact

- Affected code:
  - `ResourceSearchService` NamingSQL result enrichment path.
  - `ExpressionSpecGenerator` NamingSQL parameter binding and validation path.
  - NamingSQL parameter models if they do not already expose `is_list`; reuse `linked_field_name` for the BO field name.
  - `NamingSqlProfileLoader` return field parsing.
  - Prompt/context payloads used by ExpressionSpecGenerator for NamingSQL parameter binding.
  - Related tests under `tests/`.
- Affected behavior:
  - NamingSQL params used by SQL `IN` templates are treated as list params even when metadata is missing or conflicting.
  - NamingSQL params used by scalar comparison operators are treated as single params.
  - NamingSQL profile `return_fields` no longer includes SQL optimizer hint fragments from SELECT clauses.
  - BO field descriptions may guide business-code resolution during Expression Spec generation, but are not persisted to the final Spec.
  - Planner receives already-bound NamingSQL param values and no longer needs to infer business value semantics or cardinality.
- No new external dependencies are expected.

