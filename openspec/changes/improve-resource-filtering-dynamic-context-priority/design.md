## Context

Resource filtering currently builds a fixed-size candidate pool before LLM reranking. The first-pass scorer tokenizes `user_query`, `node_name`, and `description`, ranks resources by tag matches, and keeps up to `top_n * 5` candidates per group. The LLM filter and keyword search can only select from that candidate pool.

The bad case is a query that asks to use a `billStatement` `fromDate` context value as a naming SQL query condition. This is fragile because mixed Chinese/resource-name text can tokenize poorly, a broad `billStatement` keyword can match many sibling contexts, and fixed top limits can exclude the specific field before the planner sees it.

The difficulty router already decides whether BO and function resources are needed. It is the right place to add a query-level estimate of how many resources the request mentions, because that estimate can guide candidate limits without coupling the environment builder to LLM prompt interpretation.

## Goals / Non-Goals

**Goals:**

- Preserve existing BO/function routing behavior while adding a normalized resource count estimate.
- Use the router's resource count estimate to dynamically size context, BO, and function limits.
- Improve recall for explicit resource mentions in mixed natural-language queries, especially context area plus field references such as `billStatement` and `fromDate`.
- Give `billStatement` global context variables deterministic priority during candidate recall and tie-breaking.
- Keep fallback behavior robust when LLM routing or resource filtering is unavailable.

**Non-Goals:**

- Do not replace LLM semantic filtering with a new retrieval engine.
- Do not change planner schema or expression AST semantics.
- Do not introduce external search, embedding, or vector database dependencies.
- Do not hard-code a single `fromDate` spelling as the only supported field form.

## Decisions

### Decision 1: Add resource count to `ResourceRoute`

Extend `ResourceRoute` with an integer field such as `resource_count_hint`. The difficulty router prompt will ask the LLM to return a value equal to the number of resources explicitly mentioned in the query plus a buffer. The parser will accept multiple compatible response keys, clamp invalid or missing values to a conservative default, and preserve current behavior for older responses.

Alternative considered: estimate resource count only with local heuristics. This is useful as fallback, but the router already sees the full natural-language request and can distinguish vague semantic terms from explicit resource mentions. The implementation can still use a local minimum/default when LLM output is absent.

### Decision 2: Use route hints to size filtering limits

`ValueLogicGenerator` will convert `resource_count_hint` into `top_global_context`, `top_local_context`, `top_bo`, and `top_function` values when calling `build_filtered_environment()`. Disabled groups remain zero. Enabled groups receive at least the current default and can grow with the hint up to a bounded maximum.

Alternative considered: increase all default top limits permanently. That would make prompts noisier for simple cases and hides the signal that a query mentions multiple resources.

### Decision 3: Strengthen explicit mention recall before LLM reranking

Resource filtering should better preserve explicit resource-like terms from the user query. This includes normalized compound forms such as `billStatement`, `billstatement`, `fromDate`, `fromdate`, `FROM_DATE`, and phrases that combine a parent context area with a child field. Tokenization and scoring should normalize resource-name compounds consistently without losing existing camel-case and underscore matching.

Alternative considered: rely on LLM keyword search to extract the complete context path. That works for fully explicit `$ctx$.a.b` inputs, but it is not reliable when the query says "billStatement ... fromDate" in mixed natural-language text instead of writing the full context path.

### Decision 4: Prioritize `billStatement` global contexts

Global contexts under `$ctx$.billStatement` will receive a small deterministic priority boost during candidate scoring or tie-breaking. The boost should be limited to global context resources and should not override a stronger exact match to another explicit area. The purpose is to favor high-frequency bill statement fields when the query mentions bill statement context.

Alternative considered: put all `billStatement` fields into every candidate pool. That would guarantee visibility but increases prompt noise and weakens resource minimization.

### Decision 5: Merge tool-search results carefully with semantic fallback

If keyword search matches a broad context area, it should not discard a stronger semantic/local fallback selection for the same group. The merge behavior should prefer exact or more specific keyword matches, and preserve fallback items when tool search only matched broad parent-area terms.

Alternative considered: remove tool-search override entirely. That would regress current behavior where exact BO, naming SQL, function, or full context path mentions should be selected deterministically.

## Risks / Trade-offs

- Dynamic limits increase prompt size for complex queries -> Bound limits and only grow them from explicit resource-count hints.
- `billStatement` priority could over-favor unrelated bill fields -> Apply only as a small tie-breaker or boost when context terms are present.
- Router LLM may return noisy counts -> Clamp values and keep current defaults as fallback.
- Tokenization changes can affect existing ranking tests -> Add targeted tests for old camel-case behavior and new mixed natural-language/resource-name behavior.
- Broader candidate pools can mask bad LLM choices -> Keep invalid-ID fallback and verify final selected IDs remain candidates.

## Migration Plan

1. Extend route parsing and prompt output shape while accepting existing router responses.
2. Thread the resource count hint into environment filter limits.
3. Improve token normalization and context scoring with regression tests.
4. Adjust keyword-search merge behavior only where broad context matches currently override better fallback candidates.
5. Run the existing resource loader, environment, difficulty router, value logic, and planner tests.

Rollback is straightforward: ignore the new route field and return to fixed top limits. Tokenization and billStatement prioritization should be covered by tests so any rollback can be targeted.

## Open Questions

- What exact buffer should the router use by default: `+1`, `+2`, or a percentage-based buffer?
- What upper bound should dynamic context and BO/function limits use in production to control prompt size?
- Should other high-frequency context areas receive priority later, and if so should this become configurable resource metadata instead of code-level policy?
