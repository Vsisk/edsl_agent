# If Query Target Decomposition Plan

> Current correction: If logic is not represented inside Orchestrator.
> Orchestrator may discover the resource targets mentioned by an if-style query, but the condition and branch expression remain planner work.

**Goal:** When a query contains conditional wording, classify it before orchestration. If it is a multi-resource query, decompose only the resource targets that must be searched. Do not output `if(condition, then, else)`, condition operands, branch literals, or expression AST.

**Related design:** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

## Phase #1: Reject Expression Payloads

**Status:** Finished

Files:

- `agent/spec_orchestration/models.py`
- `agent/spec_orchestration/semantic.py`
- `tests/test_spec_orchestrator_semantic.py`

Behavior:

- Multi-goal decomposition accepts only `target_semantic_names`.
- Payloads with `operator`, `operands`, `condition`, `then`, or `else` are invalid.
- Invalid decomposition falls back to `single_goal`.

## Phase #2: Resolve Mentioned Targets

**Status:** Finished

Files:

- `agent/spec_orchestration/orchestrator.py`
- `tests/test_spec_orchestrator.py`

Behavior:

- The decomposer may return targets such as `customer is active` and `customer name`.
- Each target resolves through normal single-goal resource search.
- The root candidate is `goal_set` and carries only target names.
- No branch value, fixed fallback string, or boolean condition type is inferred by Orchestrator.

## Phase #3: Keep Spec Resource-Only

**Status:** Finished

Files:

- `agent/spec_orchestration/compiler.py`
- `tests/test_spec_orchestrator_compiler.py`

Behavior:

- The final Spec lists selected resources for each resolved goal.
- It does not say "if", "then", "else", or encode conditional orchestration.
- Planner receives the original query and performs conditional expression planning later.
