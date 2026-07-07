# Lightweight Expression Type Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse SimpleExpressionPlan string expressions with a stateful lightweight scanner and statically validate definitions and the return expression against typed context and registries.

**Architecture:** Keep syntax scanning in `expression_syntax.py` and type resolution in `expression_type_validation.py`. Reuse `TypeRef`, `TypeRegistry`, `MethodRegistry`, and `TypedExpressionContext`; return structured validation results without changing planner, ASTBuilder, validator, or renderer behavior.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest

---

### Task 1: Stateful top-level scanning and chain tokens

**Files:**
- Create: `agent/expression_generation/expression_syntax.py`
- Create: `tests/test_expression_syntax.py`

- [ ] **Step 1: Write failing splitter tests**

Add tests asserting exact output for:

```python
split_top_level_dot_chain('charge.CHARGE_AMT.long2str()')
# ['charge', 'CHARGE_AMT', 'long2str()']

split_top_level_dot_chain('charges.find{it.CHARGE_AMT > 0}.CHARGE_AMT')
# ['charges', 'find{it.CHARGE_AMT > 0}', 'CHARGE_AMT']
```

Also cover `$ctx$.address.addr1`, `dateValue("yyyy.MM.dd").addDays(1)`, `fn($ctx$.a.b).length()`, escaped quotes, and `1.23` without splitting dots inside protected regions or decimals.

- [ ] **Step 2: Run syntax tests and observe RED**

Run: `python -m pytest tests/test_expression_syntax.py -v`

Expected: collection fails because the syntax module does not exist.

- [ ] **Step 3: Implement ExpressionTokenizer and TopLevelDotSplitter**

Implement one character scanner that records quote/escape state plus parenthesis and brace depth. Emit a dot boundary only at zero depths, outside strings, and when the adjacent characters are not both digits. Expose `split_top_level_dot_chain`, `split_top_level_commas`, and `strip_balanced_call` helpers. Do not call `str.split(".")`.

- [ ] **Step 4: Add and pass ChainToken parser tests**

Test `MethodChainParser.parse` returns `root`, `field`, `method_call`, and `lambda_method_call` tokens with method arguments split at top-level commas and lambda bodies preserved. Implement:

```python
class ChainToken(BaseModel):
    token_type: Literal["root", "field", "method_call", "lambda_method_call"]
    raw: str
    name: str
    args: list[str] = Field(default_factory=list)
    lambda_expr: str | None = None
```

- [ ] **Step 5: Run syntax tests and commit**

Run: `python -m pytest tests/test_expression_syntax.py -q`

Expected: all syntax tests pass.

```powershell
git add agent/expression_generation/expression_syntax.py tests/test_expression_syntax.py
git commit -m "feat: parse top-level expression chains"
```

### Task 2: Validation models, roots, fields, and simple methods

**Files:**
- Create: `agent/expression_generation/expression_type_validation.py`
- Create: `tests/test_expression_type_validation.py`

- [ ] **Step 1: Write failing model and basic-chain tests**

Define test fixtures with `$ctx$.address: logic.Address`, `Address.addr1: basic.String`, and built-in methods. Assert:

```python
result = validator.validate(plan('$ctx$.address.addr1.length()'))
assert result.return_type == TypeRef(kind="basic", name="int")
assert result.errors == []
```

Add failures for `$ctx$.missing` (`UNKNOWN_CONTEXT_PATH`), unknown variable (`UNKNOWN_VARIABLE`), String `.xxx` (`FIELD_ACCESS_ON_BASIC_TYPE`), and String `.addDays(1)` (`METHOD_NOT_FOUND`).

- [ ] **Step 2: Run validation tests and observe RED**

Run: `python -m pytest tests/test_expression_type_validation.py -v`

Expected: collection fails because validation models and validator do not exist.

- [ ] **Step 3: Implement the public validation contract**

Add `SimpleDefinition`, `SimpleExpressionPlan`, nested `TypeScope`, `TypeValidationError`, `ExpressionValidationResult`, and `ExpressionValidationInput`. Input contains the plan, typed context, type registry, and method registry. `is_valid` is derived from an empty errors list.

- [ ] **Step 4: Implement type-text parsing and root resolution**

Parse rendered scalar/List/Map type strings from typed context into `TypeRef`. Build a root table and choose the longest exact typed context prefix. Resolve ordinary identifiers from `TypeScope`; classify missing context/local roots separately from missing variables and unsupported roots.

- [ ] **Step 5: Implement MethodChainValidator transitions**

For fields, distinguish object miss, basic access, and list direct access. For methods, recursively obtain argument literal types, use `methods_for` to classify name and arity failures, and use `match` for the final type check. Populate every error field with the full expression and failing token.

- [ ] **Step 6: Run basic validation tests and commit**

Run: `python -m pytest tests/test_expression_type_validation.py -q`

Expected: all Task-2 tests pass.

```powershell
git add agent/expression_generation/expression_type_validation.py tests/test_expression_type_validation.py
git commit -m "feat: validate expression method chains"
```

### Task 3: Binary expressions, if, and nested method arguments

**Files:**
- Modify: `agent/expression_generation/expression_syntax.py`
- Modify: `agent/expression_generation/expression_type_validation.py`
- Modify: `tests/test_expression_syntax.py`
- Modify: `tests/test_expression_type_validation.py`

- [ ] **Step 1: Write failing operator and if tests**

Assert the tokenizer locates only top-level operators and respects strings, calls, braces, and decimals. Add successful validation for:

```text
if($ctx$.address.addr1.length() > 0, $ctx$.address.addr1, "")
$ctx$.billStatement.fromDate.dateValue("yyyy.MM.dd").addDays(1).toString("yyyy.MM.dd")
```

Add `IF_CONDITION_NOT_BOOLEAN`, `IF_BRANCH_TYPE_MISMATCH`, method argument count, and method argument type tests.

- [ ] **Step 2: Run the new cases and observe RED**

Run: `python -m pytest tests/test_expression_syntax.py tests/test_expression_type_validation.py -q`

Expected: new operator and conditional assertions fail.

- [ ] **Step 3: Implement top-level operator selection**

Scan operators outside protected regions in precedence groups `||`, `&&`, comparisons, `+/-`, and `*/`. Resolve both operands recursively. Comparisons return `basic.boolean`; boolean operators require booleans; numeric arithmetic returns the wider numeric type.

- [ ] **Step 4: Implement top-level if validation**

Recognize complete `if(...)`, split exactly three top-level arguments, resolve condition and branches recursively, require `basic.boolean`, and require equal branch types. Preserve quoted date-format arguments as single String literals.

- [ ] **Step 5: Run syntax and validation tests and commit**

Run: `python -m pytest tests/test_expression_syntax.py tests/test_expression_type_validation.py -q`

Expected: all current tests pass.

```powershell
git add agent/expression_generation/expression_syntax.py agent/expression_generation/expression_type_validation.py tests/test_expression_syntax.py tests/test_expression_type_validation.py
git commit -m "feat: validate conditional and binary expressions"
```

### Task 4: Definitions, fetch types, lambda scope, and target type

**Files:**
- Modify: `agent/expression_generation/expression_type_validation.py`
- Modify: `tests/test_expression_type_validation.py`

- [ ] **Step 1: Write failing definition and lambda tests**

Build typed templates for `fetch_one(E_QUERY_CHARGE)` returning `bo.BB_BILL_CHARGE` and `fetch(E_QUERY_CHARGE)` returning `List<bo.BB_BILL_CHARGE>`. Assert ordered definitions resolve:

```text
def charge = fetch_one(...); charge.CHARGE_AMT.long2str() -> basic.String
def charges = fetch(...); charges.find{it.CHARGE_AMT > 0}.CHARGE_AMT -> basic.long
```

Add failures for direct list field access, missing lambda element type, non-boolean lambda, and target return mismatch.

- [ ] **Step 2: Run definition/lambda tests and observe RED**

Run: `python -m pytest tests/test_expression_type_validation.py -q`

Expected: new definition, fetch, lambda, and target assertions fail.

- [ ] **Step 3: Implement ordered definitions and fetch lookup**

Resolve definitions sequentially and bind only successful types. Match `fetch`/`fetch_one` names against concrete typed templates or patterns; never invent a BO type. Preserve successful `definition_types` in the result.

- [ ] **Step 4: Implement lambda method validation**

For `name{expr}`, require `List<T>`, bind child-scope `it=T`, resolve the body, require `basic.boolean`, then call the registered synthetic method name such as `find{expr}` with zero ordinary arguments. Continue the outer chain with its resolved return type.

- [ ] **Step 5: Implement final target validation and error coverage**

After resolving `return_expr`, compare it with `target_return_type`. Add `TARGET_RETURN_TYPE_MISMATCH` when unequal. Ensure every required error constant has a direct assertion and structured expected/actual/owner data where applicable.

- [ ] **Step 6: Run all feature tests and commit**

Run: `python -m pytest tests/test_expression_syntax.py tests/test_expression_type_validation.py tests/test_type_system.py tests/test_typed_expression_context.py -q`

Expected: all feature tests pass.

```powershell
git add agent/expression_generation/expression_type_validation.py tests/test_expression_type_validation.py
git commit -m "feat: validate simple expression plans"
```

### Task 5: Regression and scope verification

**Files:**
- Verify only: files changed by Tasks 1-4

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_expression_syntax.py tests/test_expression_type_validation.py tests/test_type_system.py tests/test_typed_expression_context.py -q`

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete suite**

Run: `python -m pytest -q`

Expected: no failures beyond the recorded 17 missing-sample-data baseline failures.

- [ ] **Step 3: Audit forbidden files and diff quality**

Run: `git diff --name-only 563d695..HEAD` and `git diff --check 563d695..HEAD`.

Expected: only the new expression syntax/type-validation modules and their tests are changed; planner output models, ASTBuilder, validator, and renderer are untouched, and no whitespace errors are reported.
