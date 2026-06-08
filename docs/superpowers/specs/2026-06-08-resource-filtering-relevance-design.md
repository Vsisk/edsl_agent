---
change: improve-resource-filtering-dynamic-context-priority
role: technical-design
canonical_spec: openspec
---

# Resource Filtering Relevance Technical Design

## Source Of Truth

OpenSpec remains the canonical source for requirements:

- Proposal: `openspec/changes/improve-resource-filtering-dynamic-context-priority/proposal.md`
- Design: `openspec/changes/improve-resource-filtering-dynamic-context-priority/design.md`
- Tasks: `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`
- Delta spec: `openspec/changes/improve-resource-filtering-dynamic-context-priority/specs/resource-filtering-relevance/spec.md`

This document does not redefine requirements. It turns the existing OpenSpec change into an implementation design, risk model, and test strategy.

## Upstream Context

### Goal

Improve resource filtering so explicitly mentioned resources are less likely to be dropped before LLM reranking, add a difficulty-router resource count hint for dynamic filter sizing, prioritize high-frequency `billStatement` global contexts, and preserve fallback behavior when LLM output is unavailable or invalid.

### Architecture Constraints

- The planner schema and expression AST semantics stay unchanged.
- No external search, embedding, or vector database dependency is introduced.
- Existing BO/function route behavior remains backward-compatible.
- Resource filtering still uses local scoring first, optional LLM keyword search, then optional LLM reranking.
- LLM components can fail or be unavailable; local fallback must remain useful.
- `billStatement` priority must be bounded and must not override a stronger exact match outside that context area.

### Task Boundary

Implementation is limited to regression tests, difficulty routing, dynamic resource limits, candidate recall, keyword-search merge behavior, and verification. It should not refactor unrelated planner, AST, or resource loader behavior.

## Design Questions And Decisions

### 1. Where should the resource count hint live?

Decision: add `resource_count_hint` to `ResourceRoute`.

`ResourceRoute` is already the boundary between "what kinds of resources are needed" and "how many candidates should filtering expose." Adding the hint there keeps query interpretation in the routing layer and keeps `build_filtered_environment()` focused on selecting resources from explicit limits.

Implementation detail:

- Add constants in `agent/planner/difficulty_router.py`:
  - `DEFAULT_RESOURCE_COUNT_HINT = 5`
  - `MIN_RESOURCE_COUNT_HINT = 1`
  - `MAX_RESOURCE_COUNT_HINT = 20`
- Extend `ResourceRoute`:
  - `use_bo: bool = True`
  - `use_function: bool = True`
  - `resource_count_hint: int = DEFAULT_RESOURCE_COUNT_HINT`
- Parse compatible LLM keys in order:
  - `resource_count_hint`
  - `resource_count`
  - `estimated_resource_count`
  - `mentioned_resource_count`
- Coerce strings like `"7"` to integers.
- Ignore booleans, non-numeric strings, negative values, and nulls.
- Clamp valid numbers to `[MIN_RESOURCE_COUNT_HINT, MAX_RESOURCE_COUNT_HINT]`.

Backward compatibility:

- Existing tests comparing `ResourceRoute(use_bo=False, use_function=False)` still pass because dataclass equality includes default `resource_count_hint`.
- Older LLM responses without count fields keep the default hint.

### 2. What should the router prompt ask for?

Decision: update the `difficulty_router` prompt to include a top-level integer `resource_count_hint`.

The prompt should say the value equals explicitly mentioned resources plus a buffer. It should make vague domain words not count as resources unless tied to a concrete resource name or path.

Examples that count:

- BO name: `BB_BAK_TRANS`
- naming SQL: `BB_BAK_TRANS_queryDataLoadData`
- function name: `CustCallMask`
- full context path: `$ctx$.billStatement.CUST_ID`
- context area plus field: `billStatement fromDate`

Examples that do not count by themselves:

- `query`
- `mask`
- `customer`
- `amount`
- `context`

Recommended prompt output shape:

```json
{
  "decision": "bo_only",
  "required_resources": ["context", "bo"],
  "resource_count_hint": 7,
  "reason": "needs naming SQL and billStatement fromDate context"
}
```

### 3. How should the count hint become filter limits?

Decision: convert the hint to per-group top limits in `ValueLogicGenerator`, not inside the router and not inside `build_filtered_environment()`.

This keeps each layer's responsibility clear:

- Router: interpret resource type and count from the query.
- Value generator: translate route into filtering policy for this generation flow.
- Environment builder: select resources using explicit limits.

Add helper:

```python
def _resource_limits_from_route(route: ResourceRoute) -> dict[str, int]:
    hint = clamp(route.resource_count_hint)
    context_limit = min(MAX_DYNAMIC_CONTEXT_LIMIT, max(DEFAULT_CONTEXT_LIMIT, hint))
    resource_limit = min(MAX_DYNAMIC_RESOURCE_LIMIT, max(DEFAULT_RESOURCE_LIMIT, hint))
    return {
        "top_global_context": context_limit,
        "top_local_context": context_limit,
        "top_bo": resource_limit if route.use_bo else 0,
        "top_function": resource_limit if route.use_function else 0,
    }
```

Suggested constants:

- `DEFAULT_CONTEXT_LIMIT = 5`
- `DEFAULT_RESOURCE_LIMIT = 5`
- `MAX_DYNAMIC_CONTEXT_LIMIT = 12`
- `MAX_DYNAMIC_RESOURCE_LIMIT = 10`

Rationale:

- Context variables are often more numerous and cheaper than BO/function summaries, so allow a slightly larger cap.
- BO and function resources carry richer summaries and can bloat prompts quickly, so cap lower.
- Disabled BO/function groups remain zero even when the hint is high.

### 4. How should mixed natural-language/resource-name tokenization work?

Decision: normalize resource-name forms at tag/query token extraction time while preserving existing tokens.

The current tokenizer can produce weak tokens when camel-case resource names are adjacent to non-ASCII prose. The fix should be additive: keep current token behavior and add normalized compound aliases.

Add aliases for each extracted token or segment:

- Original compound: `fromDate`
- Lower compound: `fromdate`
- Camel parts: `from`, `Date`
- Underscore compact: `FROM_DATE` -> `fromdate`
- Dot/underscore/path compact: `$ctx$.billStatement.FROM_DATE` -> `ctxbillstatementfromdate` where useful for keyword search, but avoid over-weighting this in semantic tag scoring.

Recommended implementation shape in `tag_utils.py`:

- Keep `tokenize_text()` public behavior stable.
- Add internal helper `_normalized_aliases(token_or_segment)`.
- For segments that contain ASCII letters, emit a compact alphanumeric lowercase alias when:
  - the segment has camel-case boundary, underscore, dash, dot, or mixed non-ASCII adjacency;
  - the compact alias length is at least 3;
  - the compact alias is not a stop word.
- Deduplicate in original order.

Important edge case:

- Do not treat the English stop word `from` as useless when it is part of `fromDate`. `from` alone may remain filtered, but `fromdate` must be retained.

### 5. How should context scoring recognize parent plus child mentions?

Decision: keep generic tag scoring, but add a context-specific scoring bonus for exact parent-area and child-field aliases.

The problem is not only tokenization. If many `$ctx$.billStatement.*DATE` fields match `date`, the specifically mentioned `fromDate` field needs to outrank siblings. A small context-specific bonus gives deterministic behavior without replacing the existing ranker.

Implementation approach:

- Extend `_score_resource()` to accept optional `group`.
- For global/local context groups, compute `_context_specificity_bonus(resource, weighted_tokens)`.
- Bonus inputs:
  - normalized context path parts from `context_name`
  - normalized aliases for each path part
  - weighted query tokens
- Add bonus when:
  - parent area matches, e.g. `billstatement`;
  - child field matches, e.g. `fromdate`;
  - both match, give a stronger pair bonus.

Suggested constants:

- `CONTEXT_FIELD_EXACT_BONUS = 2.0`
- `CONTEXT_PARENT_FIELD_PAIR_BONUS = 1.0`
- `BILL_STATEMENT_PRIORITY_BONUS = 0.25`

Why these magnitudes:

- Exact query token match weight is currently `3.0`.
- Field specificity should be meaningful but not dominate multiple exact matches.
- `billStatement` priority should only break ties or near-ties.

### 6. How should `billStatement` priority be applied?

Decision: apply a bounded boost only to global context resources whose path is under `$ctx$.billStatement` and only when the query mentions bill statement context or the resource already has a positive score.

Implementation rule:

- Resource must be a `ContextRegistry`.
- `context_name.lower().startswith("$ctx$.billstatement.")`.
- Query tokens include one of:
  - `billstatement`
  - `bill`
  - `statement`
  - `bbbillstatement`
  - `bb_bill_statement` normalized alias if available.
- Add `BILL_STATEMENT_PRIORITY_BONUS` to score.

Tie-breaking alternative:

- Instead of score boost, add `priority_score` to `_ScoredResource` and sort by it after exact matches. This is cleaner if we want priority to be explicitly weaker than score.

Recommendation:

- Prefer explicit `priority_score` in `_ScoredResource`.
- Sort key:
  1. `-score`
  2. `-exact_matches`
  3. `-query_score`
  4. `-priority_score`
  5. `index`

This keeps priority from overriding a stronger score. If tests show near-ties still miss `fromDate`, use a small score bonus for field specificity and reserve `priority_score` for bill area.

### 7. How should keyword search merge avoid broad-match damage?

Decision: classify keyword-search commands by specificity before deciding whether they override fallback.

Current behavior replaces an entire matched group with tool-search results. That is correct for exact resource names and full context paths, but risky for broad context area keywords like `billStatement`.

Add command specificity:

- Exact context path:
  - keyword starts with `$ctx$.`, `$local$.`, or `$iter$.`
  - or compact keyword includes at least three path parts and matches one context exactly.
- Broad context area:
  - keyword is a parent area such as `billStatement`
  - keyword matches multiple sibling context resources.
- Exact BO/function/naming SQL:
  - preserve existing deterministic behavior.

Implementation options:

1. Add metadata to `_ToolSearchResult`, such as `match_specificity_by_group`.
2. Store selected resources plus a `broad_match_groups` set.
3. In `_merge_tool_search_and_fallback()`, for broad context groups, merge fallback first and then add tool results until limit.

Recommended merge for broad context:

```text
final = []
append fallback selected resources in order
append tool-search selected resources not already present
truncate to limit
```

Recommended merge for exact context path:

```text
final = []
append exact tool-search selected resources
append fallback selected resources not already present
truncate to limit
```

This preserves deterministic exact-path selection and prevents broad parent matches from discarding a specific field selected by semantic fallback.

## Implementation Plan Shape

### Phase 1: Tests First

Add failing tests before changing implementation:

- `tests/test_difficulty_router.py`
  - parses `resource_count_hint`
  - accepts compatible aliases
  - clamps invalid and out-of-range values
  - preserves old route responses
- `tests/test_value_logic_generator.py`
  - route hint changes `top_global_context/top_local_context/top_bo/top_function`
  - disabled BO/function groups remain zero
- `tests/test_environment.py`
  - synthetic context registry with `$ctx$.billStatement.FROM_DATE`, sibling date fields, and unrelated exact-match context
  - query without full path selects `FROM_DATE`
  - broad keyword search does not drop fallback-selected `FROM_DATE`
  - exact `$ctx$.billStatement.FROM_DATE` keyword remains deterministic
- `tests/test_resource_search_tool.py` or tag utility coverage
  - `fromDate`, `fromdate`, `FROM_DATE` normalize compatibly
  - mixed non-ASCII prose adjacent to resource names still yields useful aliases

### Phase 2: Router And Prompt

- Add `resource_count_hint` to `ResourceRoute`.
- Parse and clamp count hints.
- Update `prompt.json` `difficulty_router`.
- Keep all existing response shapes accepted.

### Phase 3: Dynamic Limits

- Add limit helper to `ValueLogicGenerator`.
- Pass explicit `top_global_context` and `top_local_context`.
- Replace hard-coded `top_bo=5 if route.use_bo else 0` with helper output.
- Preserve exception fallback by returning default `ResourceRoute()`.

### Phase 4: Token And Score Improvements

- Add additive normalized aliases.
- Add context path part normalization.
- Add context-specific field/parent scoring bonus.
- Add billStatement priority score or bounded bonus.

### Phase 5: Tool Search Merge

- Classify context keyword specificity.
- Merge broad context results with fallback instead of replacing the whole group.
- Preserve exact path and exact BO/function/naming SQL override behavior.

### Phase 6: Verification

Run:

```powershell
python -m unittest tests.test_difficulty_router tests.test_environment tests.test_value_logic_generator
python -m unittest tests.test_planner_prompt tests.test_resource_loader tests.test_llm_planner tests.test_resource_search_tool
openspec status --change "improve-resource-filtering-dynamic-context-priority"
```

Also run a manual smoke case using a synthetic registry where:

- `$ctx$.billStatement.TO_DATE`
- `$ctx$.billStatement.START_DATE`
- `$ctx$.billStatement.END_DATE`
- `$ctx$.billStatement.FROM_DATE`

all exist, and the query asks for `billStatement` `fromDate` as a naming SQL condition. Confirm `FROM_DATE` appears in `selected_global_contexts`.

## Technical Risks

### Risk: Token aliases increase false positives

Mitigation:

- Only add compact aliases for ASCII-like resource segments.
- Keep stop-word filtering for standalone tokens.
- Use field-specific bonus only for context resources, not all resource groups.

### Risk: Dynamic limits bloat prompts

Mitigation:

- Clamp route hints.
- Use separate caps for context and BO/function.
- Keep disabled groups at zero.

### Risk: `billStatement` priority hides better matches

Mitigation:

- Make priority a tie-breaker or very small bonus.
- Add explicit test where a non-billStatement exact context must win.

### Risk: Keyword merge changes exact selection semantics

Mitigation:

- Classify exact path/name commands separately.
- Preserve deterministic exact override for BO, naming SQL, function, and full context path.
- Only broad context area commands use fallback-first merge.

### Risk: LLM prompt changes break parser compatibility

Mitigation:

- Parser accepts old and new response shapes.
- Invalid/missing count uses defaults.
- Unit tests cover legacy responses.

## Boundary Conditions

- Query has no explicit resource names: use default hint and local scoring.
- Query mentions only context: BO/function groups remain disabled if router says context-only.
- Query mentions naming SQL and context: BO enabled, context limits grow, function may stay disabled.
- Query mentions multiple functions: function limit grows up to cap.
- `fromDate` exists as `fromdate`, `fromDate`, `FROM_DATE`, or `FROMDATE`: matching should work through aliases.
- `billStatement.fromDate` does not exist in registry: system must not fabricate a context resource.
- LLM keyword search returns invalid IDs: existing invalid-ID fallback behavior remains.
- LLM keyword search throws: fallback semantic/local selection remains.
- Current node local contexts include `fromDate`: local and global context candidates should both be eligible; final planner receives selected resources only.

## Test Strategy

Use unit tests over integration tests for most behavior because the bad case is in deterministic pre-LLM filtering. Fake LLM filters should drive specific tool-search and rerank outputs so tests remain stable.

Recommended test fixtures:

- A synthetic `LoadedResource` or temporary `ResourceLoader` payload with many sibling bill statement date fields.
- `FakeResourceFilter` with broad keyword command: `{"group": "global_context", "keyword": "billStatement"}`.
- `FakeResourceFilter` with exact keyword command: `{"group": "global_context", "keyword": "$ctx$.billStatement.FROM_DATE"}`.
- `FakeDifficultyRouter` route containing `resource_count_hint=9`.

Assertions should inspect:

- `resource_filter.calls[0]["limits"]`
- `resource_filter.calls[0]["candidates"]`
- `filtered_env.selected_global_context_ids`
- selected context names, not only IDs, because registry order can change.

## Delta Spec Review

The delta spec already contains at least one `#### Scenario` under every requirement. No OpenSpec delta spec supplement is needed for this design pass.

## Recommended Implementation Order

1. Add tests for router count parsing and dynamic limit threading.
2. Implement router field and parser.
3. Implement dynamic limit helper.
4. Add token normalization tests.
5. Implement token aliasing.
6. Add context recall and billStatement priority tests.
7. Implement context-specific scoring.
8. Add broad keyword merge tests.
9. Implement merge specificity.
10. Run full verification.
