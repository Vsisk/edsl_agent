## Context

`TypedExpressionContextBuilder` currently creates selected global-context roots before visible local roots, expands every structured root eagerly, attaches method signatures to every root and field, and finally applies one sequential `max_items` truncation pass. This makes the truncation outcome depend on construction order, allows a large early root to starve nearer lexical scopes, and repeats basic-type method metadata even though `method_catalog` already groups signatures by owner type.

The expression parser and validator require enough information to resolve complete access paths. The planner prompt benefits from full paths, but it does not require methods to be repeated on each value. The change must preserve the hard item ceiling and deterministic output.

## Goals / Non-Goals

**Goals:**

- Preserve explicitly requested paths and prioritize `$iter$`, `$local$`, then `$ctx$` under pressure.
- Prevent one large structured root from starving other important roots.
- Spend tokens on unique semantic information by publishing methods once per referenced type.
- Keep field selection relevant, deterministic, testable, and within `max_items`.
- Make budget-driven omission visible to diagnostics.

**Non-Goals:**

- Replacing the upstream resource filtering or semantic ranker.
- Introducing tokenization-model-specific byte or token counting.
- Normalizing all BO/logic/extattr field definitions into a new shared type catalog in this change.
- Changing expression syntax, scope semantics, or validation rules.

## Decisions

### Classify roots before budgeting

The builder will construct candidates and assign an admission key instead of relying on append order. Explicit query references form the highest tier. Remaining context roots are classified as iterator, local, and global from their canonical path and `property_type`; functions and derived templates follow context roots.

Within a tier, existing query, node-name, and annotation relevance signals are used, followed by a stable expression/name key. Exact explicit paths are detected conservatively from the query rather than inferred semantically.

Alternative considered: only reorder the current loops. This is insufficient because field expansion and sequential truncation still let the first large root consume all detail slots.

### Reserve roots before allocating details

Budget application will use two logical passes:

1. Admit prioritized root and variable-template skeletons while budget remains.
2. Allocate remaining slots to their pre-ranked fields in priority order, then add referenced method-catalog entries and expression patterns.

The output retains grouped fields under each admitted root even though fields are selected in a later pass. No rigid per-scope numeric quota is introduced; unused capacity naturally flows to lower-priority candidates. Explicitly referenced roots receive priority but do not bypass the hard `max_items` ceiling.

Alternative considered: fixed percentages for iterator, local, and global data. Fixed quotas waste capacity when a scope is absent and introduce configuration without evidence that one ratio suits all nodes.

### Keep complete access views but remove per-value methods

`TypedRootValue` and `TypedAccessView` will retain expression/access and return type, but their repeated `methods` fields will be removed from the serialized model. `method_catalog` remains the authoritative method representation, keyed by rendered owner type and filtered to types present in emitted roots, fields, or templates.

This is a deliberate serialized-shape change internal to the planner prompt. Parser and validator behavior remains type-registry-based. Prompt fixtures and any direct model constructors must migrate together.

Alternative considered: introduce a fully normalized type catalog for both fields and methods. That offers larger future savings for repeated composite types, but it would require a broader prompt and validation migration. It is deferred until measurements show the remaining duplication warrants it.

### Report budget truncation once

The budget pass will track whether any otherwise applicable root, field, method view, or pattern was omitted. It will append one stable warning rather than a warning per omitted item, avoiding a new source of token growth.

## Risks / Trade-offs

- [Removing per-value `methods` breaks prompt fixtures or callers constructing those models] → Update all repository consumers and add serialization regression tests in the same change.
- [Root reservation can leave fewer slots for highly relevant fields] → Explicit matches rank first and the behavior is covered by constrained-budget scenarios.
- [Literal query matching can miss aliases] → Keep exact-path promotion conservative and rely on existing relevance scoring within tiers; upstream semantic filtering remains unchanged.
- [Warnings themselves consume prompt space] → Emit a single compact deterministic warning only when truncation occurs.
- [Item counts only approximate real model tokens] → Retain the existing predictable contract now; token-estimator-based budgeting remains a separate concern.

## Migration Plan

1. Add failing tests for priority, two-stage admission, deterministic detail ranking, catalog deduplication, and truncation warnings.
2. Change the typed-context view models and update direct constructors/fixtures.
3. Implement classified candidates and two-stage budgeting while preserving the hard ceiling.
4. Update prompt serialization expectations and run focused plus full test suites.

Rollback is a single-code-change revert because no persistent data or external contract is migrated.

## Open Questions

- After this change is measured, should repeated BO/logic/extattr field structures move to a shared type catalog as a follow-up?
- Should a future budget use estimated model tokens in addition to the deterministic item ceiling?
