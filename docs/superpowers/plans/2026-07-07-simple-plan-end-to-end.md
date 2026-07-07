# Simple Plan End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the default expression planner produce SimpleExpressionPlan, validate it locally, and render validated EDSL with structured failure/debug results.

**Architecture:** Add a simple planner and prompt, a narrow validator facade, lightweight AST models/builder, and EDSLRenderer. Integrate them in ValueLogicGenerator while retaining the existing Plan path for injected legacy planners.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest

---

### Task 1: Lightweight AST and renderer

**Files:**
- Modify: `agent/expression_generation/ast/builder.py`
- Create: `agent/expression_generation/edsl_renderer.py`
- Create: `tests/test_simple_plan_renderer.py`

- [ ] Write failing tests for `build_simple_ast` and rendering zero, one, and multiple ordered definitions.
- [ ] Run `python -m pytest tests/test_simple_plan_renderer.py -q`; expect missing APIs.
- [ ] Add `SimpleDefinitionAst`, `SimpleExpressionProgramAst`, `build_simple_ast`, and `EDSLRenderer.render_simple_plan`. Validate identifier names and nonblank strings; render `def name: expr;` lines followed by verbatim return expression.
- [ ] Re-run the tests; expect PASS.
- [ ] Commit with `git commit -m "feat: render validated simple plans"`.

### Task 2: Simple planner and prompt

**Files:**
- Create: `agent/planner/simple_expression_planner.py`
- Modify: `prompt.json`
- Create: `tests/test_simple_expression_planner.py`

- [ ] Write a failing fake-client test asserting typed context appears in the prompt and strict JSON validates as `SimpleExpressionPlan`.
- [ ] Run the test; expect the planner module to be missing.
- [ ] Implement `SimpleExpressionPlanner.plan(node_info, user_query, filtered_env, typed_context)` using `generate_by_llm`, bounded serialized inputs, and a new `simple_expression_planner` prompt that permits only definitions, return_expr, and target_return_type.
- [ ] Re-run the test and validate `prompt.json` with `python -m json.tool prompt.json`.
- [ ] Commit with `git commit -m "feat: plan simple expressions"`.

### Task 3: Validator facade and result models

**Files:**
- Create: `agent/expression_generation/simple_plan_validator.py`
- Modify: `agent/models.py`
- Create: `tests/test_simple_plan_validator.py`

- [ ] Write failing tests for the facade and `ValueLogicResult(logic_type="validation_failed")` with structured errors/debug fields.
- [ ] Run the tests; expect missing facade/result fields.
- [ ] Add `SimplePlanRuntime(type_registry, method_registry)` and `SimplePlanValidator.validate_simple_plan`, delegating to MethodChainValidator. Add `debug` to ValueLogicRequest and optional `validation_errors`/`debug_info` plus the new logic type to ValueLogicResult.
- [ ] Re-run tests; expect PASS.
- [ ] Commit with `git commit -m "feat: expose simple plan validation results"`.

### Task 4: Main-flow integration and end-to-end cases

**Files:**
- Modify: `agent/value_logic_generator.py`
- Create: `tests/test_simple_expression_end_to_end.py`

- [ ] Write four failing deterministic-planner tests for context method, query variable, List.find, and invalid String.addDays; use a renderer spy to prove invalid plans are not rendered.
- [ ] Add debug assertions for typed_context, simple_plan, and type_validation_result.
- [ ] Run the new tests; expect current generator to route SimpleExpressionPlan into legacy ASTBuilder and fail.
- [ ] Make SimpleExpressionPlanner the default. Branch on planner result type: existing Plan uses legacy flow; SimpleExpressionPlan validates, returns structured failure on errors, otherwise builds lightweight AST and renders. Populate debug_info only when request.debug is true.
- [ ] Run new tests plus existing value-logic, planner, AST, and renderer tests.
- [ ] Commit with `git commit -m "feat: integrate validated simple expression flow"`.

### Task 5: Verification

- [ ] Run focused tests for simple planner, renderer, validator, end-to-end, and prior type infrastructure.
- [ ] Run `python -m pytest -q`; expect only the recorded 17 missing-sample-data baseline failures.
- [ ] Run `git diff --check c70f830..HEAD` and audit changed files. Confirm the existing Plan schema and legacy renderer remain unchanged.
