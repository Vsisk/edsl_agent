## 1. Regression Coverage

- [x] 1.1 Add difficulty router tests for parsing a valid resource count hint and falling back when the hint is missing or invalid.
- [x] 1.2 Add value logic generator tests that verify route resource count hints change filtering limits while disabled BO/function groups remain zero.
- [x] 1.3 Add environment filtering tests for a `billStatement.fromDate` context used as a naming SQL parameter without a full `$ctx$` path.
- [x] 1.4 Add environment filtering tests for mixed natural-language/resource-name tokenization around `billStatement` and `fromDate`.
- [ ] 1.5 Add keyword search merge tests showing broad `billStatement` matches preserve a more specific fallback-selected field, while exact full-path matches remain deterministic.

## 2. Difficulty Routing

- [x] 2.1 Extend `ResourceRoute` with a bounded `resource_count_hint` field and preserve current defaults for existing call sites.
- [x] 2.2 Update `_route_from_response()` to parse compatible resource count keys, clamp invalid values, and keep BO/function route parsing backward-compatible.
- [x] 2.3 Update the `difficulty_router` prompt in `prompt.json` to require a resource count value equal to explicit query resource mentions plus buffer.
- [x] 2.4 Document or encode default, minimum, and maximum resource count hint constants near the router parsing logic.

## 3. Dynamic Filtering Limits

- [x] 3.1 Add a small helper in `ValueLogicGenerator` to convert `resource_count_hint` into `top_global_context`, `top_local_context`, `top_bo`, and `top_function` values.
- [x] 3.2 Thread dynamic context limits into `build_filtered_environment()` instead of relying on fixed default context limits.
- [x] 3.3 Keep disabled BO/function groups at zero regardless of the resource count hint.
- [x] 3.4 Bound all dynamic limits to avoid unbounded prompt growth.

## 4. Candidate Recall Improvements

- [x] 4.1 Improve token normalization so camel-case, all-lowercase, and underscore forms like `fromDate`, `fromdate`, and `FROM_DATE` can match each other.
- [x] 4.2 Preserve mixed natural-language/resource-name tokens without breaking existing stop-word filtering behavior.
- [x] 4.3 Add context scoring support for recognizing parent-area plus child-field mentions such as `billStatement` plus `fromDate`.
- [x] 4.4 Add a deterministic `billStatement` global context priority boost or tie-breaker that only applies when bill statement context is relevant.
- [x] 4.5 Ensure a stronger exact match outside `billStatement` can still outrank the `billStatement` priority boost.

## 5. Keyword Search Merge Behavior

- [ ] 5.1 Distinguish exact full-path context keyword matches from broad parent-area context keyword matches.
- [ ] 5.2 Merge broad context keyword-search results with fallback selections instead of replacing the whole group.
- [ ] 5.3 Preserve current deterministic override behavior for exact BO names, naming SQL names, function names, and full context paths.

## 6. Verification

- [ ] 6.1 Run `python -m unittest tests.test_difficulty_router tests.test_environment tests.test_value_logic_generator`.
- [ ] 6.2 Run related planner/resource loader tests if prompt or tag changes affect snapshots: `python -m unittest tests.test_planner_prompt tests.test_resource_loader tests.test_llm_planner`.
- [ ] 6.3 Manually inspect the generated filtered environment for the `billStatement.fromDate` naming SQL bad case and confirm the expected context is present.
- [ ] 6.4 Run `openspec status --change "improve-resource-filtering-dynamic-context-priority"` and confirm the change is apply-ready.
