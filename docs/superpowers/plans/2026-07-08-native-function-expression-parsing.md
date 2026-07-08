# Native Function Expression Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse typed-context native function roots such as `DateUtils.format(value, pattern)` into the existing generic call Plan/AST nodes and preserve them through rendering.

**Architecture:** `EDSLExpressionParser` will index `source_type="function"` roots separately, recognize only those qualified names as native calls, recursively parse their arguments, and then attach any trailing member chain to the call receiver. Existing Plan models, AST models, builder, validator, and renderer remain unchanged.

**Tech Stack:** Python 3, Pydantic, pytest, existing expression syntax utilities and Plan/AST pipeline.

---

### Task 1: Typed native call parsing

**Files:**
- Modify: `agent/expression_generation/edsl_expression_parser.py`
- Test: `tests/test_edsl_expression_parser.py`

- [ ] **Step 1: Write failing parser tests**

Add tests constructing `TypedExpressionContext` with `TypedRootValue(expr="Text.mask", source_type="function", return_type="basic.String")`. Assert `Text.mask($ctx$.name, "x")` becomes a `CallExprPlanNode` with qualified name and recursively parsed arguments. Add nested-call and `.length()` suffix cases, plus an unregistered `Other.mask(...)` case that remains a member method call.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_edsl_expression_parser.py -q`

Expected: new native-call assertions fail because the parser currently treats the function class as a variable receiver.

- [ ] **Step 3: Implement typed-root native call parsing**

In `EDSLExpressionParser.__init__`, create a longest-name-first collection from roots whose `source_type` is `function`. Add a delimiter-aware helper that finds the closing parenthesis while respecting nested parentheses, braces, and quoted strings. Add `_parse_native_call` that:

```python
return {
    "type": "call",
    "name": qualified_name,
    "args": [self.parse_expression(arg) for arg in split_top_level_commas(arguments)],
}
```

If a suffix remains, feed its top-level member tokens into the existing chain-node construction using the call dictionary as the initial receiver.

- [ ] **Step 4: Run parser tests**

Run: `python -m pytest tests/test_edsl_expression_parser.py -q`

Expected: all parser tests pass.

- [ ] **Step 5: Commit parser behavior**

```powershell
git add agent/expression_generation/edsl_expression_parser.py tests/test_edsl_expression_parser.py
git commit -m "feat: parse typed native function calls"
```

### Task 2: End-to-end AST round trip and failure handling

**Files:**
- Test: `tests/test_simple_expression_end_to_end.py`

- [ ] **Step 1: Write end-to-end tests**

Add a test whose typed context exposes `Text.mask` and whose SimplePlan returns `Text.mask($ctx$.name, "x").length()`. Assert the final expression is identical. Add a malformed typed native invocation with an unmatched parenthesis and assert `logic_type="validation_failed"` and `error_type="PARSE_FAILED"`.

- [ ] **Step 2: Run tests and observe any gap**

Run: `python -m pytest tests/test_simple_expression_end_to_end.py -q`

Expected: round-trip passes after Task 1; malformed input either passes incorrectly or fails structurally until strict malformed-call handling is complete.

- [ ] **Step 3: Complete strict malformed-call handling**

When a function root is followed by `(` but no matching top-level `)` exists, raise:

```python
raise ValueError(f"unclosed native function call: {qualified_name}")
```

Reject a non-dot suffix after the call with a `ValueError` so `ValueLogicGenerator` maps it to `PARSE_FAILED`.

- [ ] **Step 4: Run focused regression tests**

Run: `python -m pytest tests/test_edsl_expression_parser.py tests/test_simple_expression_end_to_end.py tests/test_expression_ast_builder.py tests/test_expression_validator.py tests/test_expression_generator.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit end-to-end coverage**

```powershell
git add agent/expression_generation/edsl_expression_parser.py tests/test_simple_expression_end_to_end.py
git commit -m "test: cover native function expression pipeline"
```

### Task 3: Final verification

**Files:**
- Verify only

- [ ] **Step 1: Check formatting and unintended changes**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors and only intended files are changed.

- [ ] **Step 2: Run expression-generation regression suite**

Run: `python -m pytest tests/test_edsl_expression_parser.py tests/test_simple_expression_end_to_end.py tests/test_expression_syntax.py tests/test_expression_ast_builder.py tests/test_expression_validator.py tests/test_expression_generator.py -q`

Expected: all tests pass.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`

Expected: all repository tests pass, excluding explicitly skipped tests.

