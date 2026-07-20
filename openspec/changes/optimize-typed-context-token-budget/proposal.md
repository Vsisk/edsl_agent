## Why

Typed Expression Context can exceed practical prompt token budgets when many visible resources or large structured types are expanded. The current global-first, single-pass truncation can spend the budget on `$ctx$` resources before nearer `$iter$` and `$local$` values, while repeated basic-type method metadata further inflates the payload.

## What Changes

- Introduce deterministic, near-to-far typed-context prioritization: explicit query references first, followed by `$iter$`, `$local$`, and `$ctx$` resources.
- Split budgeting into root admission and field-detail expansion so important nearby roots remain visible even when a single structured type has many fields.
- Rank fields within each scope by explicit path/name matches and existing semantic relevance signals before stable fallback ordering.
- Emit basic-type method metadata once per referenced type through the method catalog instead of repeating it on every root and field.
- Preserve the existing total item budget and local expression validation behavior while making truncation observable through warnings.

## Capabilities

### New Capabilities

- `typed-context-token-budgeting`: Defines scope-aware admission, detail allocation, metadata deduplication, and deterministic truncation for Typed Expression Context.

### Modified Capabilities

None.

## Impact

- Affects `agent/expression_generation/typed_context.py`, planner prompt serialization, and typed-context tests.
- Changes the serialized Typed Expression Context shape by removing repeated per-value method lists in favor of the existing type-level method catalog; prompt consumers and tests must be updated together.
- No new runtime dependency or external API is introduced.
