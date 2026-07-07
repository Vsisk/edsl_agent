# Simple Plan Existing AST Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse validated SimpleExpressionPlan strings into the existing Plan model and run the existing ASTBuilder, AST validator, and expression generator.

**Architecture:** Extend Plan/AST unions with field-access and member-method nodes, add an EDSLExpressionParser that produces ordinary Plan nodes, then replace the lightweight rendering branch with the standard Plan→AST→validate→generate pipeline.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest

---

### Task 1: Plan and AST member nodes

**Files:** `agent/planner/models.py`, `agent/expression_generation/ast/nodes.py`, `agent/expression_generation/ast/builder.py`, `agent/expression_generation/ast/validator.py`, `agent/expression_generation/ast/generator.py`, related tests.

- [ ] Write failing tests for `FieldAccessExprPlanNode` and `MethodCallExprPlanNode`, including ordinary and lambda methods.
- [ ] Add corresponding AST nodes and recursive union rebuilds.
- [ ] Extend builder, validator, and generator. Render field access as `receiver.field`, ordinary methods as `receiver.name(args)`, and lambdas as `receiver.name{expr}`.
- [ ] Change existing DefNode generation to required `def name: expr;` syntax and update its focused expectation.
- [ ] Run AST/model/generator tests and commit `feat: add member expression ast nodes`.

### Task 2: EDSLExpressionParser

**Files:** create `agent/expression_generation/edsl_expression_parser.py`, create `tests/test_edsl_expression_parser.py`.

- [ ] Write failing parser tests for context chains, definition variables, `if`, comparisons, date-format strings, fetch/fetch_one pair bindings, and List.find lambda.
- [ ] Implement recursive parsing using ExpressionTokenizer/MethodChainParser; do not use dot splitting outside the existing stateful splitter.
- [ ] Parse SimplePlan definitions into top-level Def nodes and return_expr into a final Return node.
- [ ] Assert parsed output validates as the existing `Plan` model; run tests and commit `feat: parse simple plans into plan nodes`.

### Task 3: Main-flow replacement

**Files:** `agent/value_logic_generator.py`, `tests/test_simple_expression_end_to_end.py`, remove or retire lightweight renderer tests/module where no longer used.

- [ ] Update end-to-end tests to spy on parser/build_ast/validate_ast/generate_expression and prove validation failure stops before parsing.
- [ ] Replace `build_simple_ast + EDSLRenderer` with `EDSLExpressionParser.parse_plan + build_ast + validate_ast + generate_expression`.
- [ ] Keep debug and structured validation failure behavior unchanged.
- [ ] Run all new and legacy expression tests and commit `feat: route simple plans through ast pipeline`.

### Task 4: Verification

- [ ] Run focused parser, AST, validator, generator, and end-to-end tests.
- [ ] Run the full suite; require zero failures in the main workspace.
- [ ] Audit diff quality and confirm SimpleExpressionPlan is never rendered directly in the main flow.
