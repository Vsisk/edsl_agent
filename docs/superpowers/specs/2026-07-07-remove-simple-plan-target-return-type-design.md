# Remove SimplePlan Target Return Type Design

## Decision

Remove `target_return_type` from the complete value-expression generation path. Target datatype is not part of expression planning and must not be guessed by the LLM or inferred from node datatype configuration.

## Changes

- `SimpleExpressionPlan` contains only ordered `definitions` and `return_expr`.
- `SimpleExpressionPlanner` prompt and example JSON do not mention or request datatype or `TypeRef` output.
- Local validation continues to infer expression types for reference, field, method, lambda, conditional, and binary checks, but performs no target return-type comparison.
- Remove the `TARGET_RETURN_TYPE_MISMATCH` branch and its tests.
- Debug serialization contains the simplified plan and inferred validation result only; it does not add target datatype metadata.
- Existing node-generation `data_type_config` behavior is outside scope and remains unchanged.

## Verification

Tests assert that planner output containing `target_return_type` is rejected as an extra field, prompt text contains no target datatype request, and the value-generation path succeeds without target datatype metadata. The complete project suite must remain green.
