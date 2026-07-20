## 1. Priority and Budget Regression Tests

- [x] 1.1 Add constrained-budget tests proving explicit query paths are retained ahead of non-explicit resources.
- [x] 1.2 Add tests proving root admission follows `$iter$`, `$local$`, `$ctx$` distance order and a large iterator cannot hide an eligible local root.
- [x] 1.3 Add tests proving field-detail selection uses relevance with deterministic fallback ordering while total emitted items remain within `max_items`.

## 2. Method Metadata Deduplication

- [x] 2.1 Add serialization tests proving repeated basic return types produce one referenced `method_catalog` entry and no per-root or per-field method lists.
- [x] 2.2 Remove repeated method fields from typed root/access view models and update builders, prompt fixtures, and direct model constructors.
- [x] 2.3 Filter and deterministically order method-catalog entries to the return types present after budgeting.

## 3. Scope-Aware Two-Stage Budgeting

- [x] 3.1 Classify candidate roots by explicit reference and lexical scope, with stable relevance ordering inside each tier.
- [x] 3.2 Refactor item budgeting into root/template admission followed by prioritized field-detail allocation, catalog emission, and pattern emission.
- [x] 3.3 Track budget-driven omissions and emit one deterministic truncation warning without exceeding the hard item ceiling.

## 4. Integration Verification

- [x] 4.1 Update planner prompt and end-to-end typed-expression tests for the deduplicated serialized context.
- [x] 4.2 Run focused typed-context, parser, validator, planner, and simple-expression tests and resolve regressions.
- [x] 4.3 Run the full test suite and confirm the OpenSpec change remains apply-ready.
