# Expression Goal Decomposition Implementation Plan

> Current correction: Orchestrator only decomposes query text into resource goals.
> It must not model concat, separators, operands, expression order, or any expression AST.

**Goal:** Before resource search, classify the query as fixed string, single goal, or multi goal. Fixed string returns directly. Single goal uses normal recursive resolution. Multi goal only outputs independent target semantic names; each target is resolved as a normal single goal and the committed resources are merged.

**Related design:** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**Scope:** Support flexible fixed-string handling and multiple resource targets such as `first name` and `last name`. String concatenation itself stays out of `ExpressionSpec.nl` and out of the Orchestrator goal graph; Planner receives the original query and performs expression orchestration later.

## Phase #1: Query Classification

**Status:** Finished

Files:

- `agent/spec_orchestration/models.py`
- `agent/spec_orchestration/semantic.py`
- `tests/test_spec_orchestrator_semantic.py`

Behavior:

- `fixed_string` carries only `fixed_value`.
- `single_goal` does not call the multi-goal decomposer.
- `multi_goal` calls a second LLM prompt and accepts only `target_semantic_names`.
- Payloads containing `operator`, `operands`, `concat`, separators, or expression AST fields are rejected by schema and fall back to `single_goal`.

## Phase #2: Parallel Target Resolution

**Status:** Finished

Files:

- `agent/spec_orchestration/orchestrator.py`
- `tests/test_spec_orchestrator.py`

Behavior:

- Each target semantic name creates one independent intermediate `ValueGoal`.
- Each target uses the same single-goal resource priority: `ctx -> bo field -> function -> literal`.
- Target branches resolve in parallel with independent trace and rollback state.
- The root resolution is a neutral `goal_set`, not a concat/composition expression.

## Phase #3: Spec And Environment Compilation

**Status:** Finished

Files:

- `agent/spec_orchestration/compiler.py`
- `tests/test_spec_orchestrator_compiler.py`

Behavior:

- Compiler merges committed resources from all target goals.
- `ExpressionSpec.nl` describes selected resources only.
- Concat, separators, order, and expression-level orchestration are not written into Spec.
- Planner uses the original `request.query` to build the final expression.
