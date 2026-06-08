## Why

Resource filtering can miss context variables that users reference indirectly, such as using a `billStatement.fromDate` context value as a naming SQL parameter. The current fixed candidate limits, weak handling of mixed natural-language/resource mentions, and equal treatment of high-frequency `billStatement` context fields make the resource environment brittle for downstream planning.

## What Changes

- Improve resource candidate recall so explicitly mentioned context paths, parent context areas, field names, BO names, naming SQL names, and function names are less likely to be dropped before LLM reranking.
- Extend the difficulty router output with an estimated resource count derived from the user query, calculated as mentioned resource count plus a buffer, so resource filtering can size `top_*` limits dynamically.
- Prioritize `billStatement` global context variables during context candidate recall because they are global, high-frequency fields that should win ties over less relevant context areas.
- Preserve existing fallback behavior when the LLM is unavailable or returns invalid IDs, while making the local candidate pool more faithful to the query.
- Add regression coverage for the `billStatement.fromDate` naming SQL parameter bad case and for dynamic limit routing behavior.

## Capabilities

### New Capabilities
- `resource-filtering-relevance`: Defines how resource routing and filtering should estimate required resource volume, recall explicitly mentioned resources, and prioritize high-value global context areas.

### Modified Capabilities

## Impact

- Affected code:
  - `agent/planner/difficulty_router.py`
  - `prompt.json`
  - `agent/value_logic_generator.py`
  - `agent/environment/environment.py`
  - `agent/resource_manager/loader/tag_utils.py`
  - resource filtering tests under `tests/`
- Affected behavior:
  - Resource limits become query-sensitive instead of fixed defaults.
  - `billStatement` context fields receive deterministic recall priority.
  - Mixed Chinese and resource-name queries receive more robust candidate matching.
- No new external dependencies are expected.
