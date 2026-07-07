# Typed Expression Context Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert existing filtered resources into a bounded typed expression context and expose it to the unchanged planner output flow.

**Architecture:** Extend the task-1 registries with read-only enumeration, then add a standalone builder that resolves selected resources from `LoadedResource` and recursively expands every branch to basic leaves. Pass the resulting Pydantic context into the planner prompt as bounded JSON while leaving Plan, ASTBuilder, validation, and rendering unchanged.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest

---

### Task 1: Registry enumeration for builder consumption

**Files:**
- Modify: `agent/expression_generation/type_system.py`
- Modify: `tests/test_type_system.py`

- [ ] **Step 1: Write failing registry enumeration tests**

Add tests proving `TypeRegistry.resolve_fields(owner)` returns the registered BO field mapping and `MethodRegistry.methods_for(owner)` returns concrete resolved method records only for that owner. Verify `List<bo.BB_BILL_CHARGE>` resolves `first/find/findAll/size`, while `basic.String` resolves only String methods.

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `python -m pytest tests/test_type_system.py -v`

Expected: FAIL because `resolve_fields`, `ResolvedMethod`, and `methods_for` do not exist.

- [ ] **Step 3: Implement read-only enumeration**

Add `TypeRegistry.resolve_fields(owner_type) -> dict[str, TypeRef]`, returning a shallow copy. Extend `MethodSig` with `arg_names: list[str] = Field(default_factory=list)` and add:

```python
class ResolvedMethod(BaseModel):
    name: str
    arg_types: list[TypeRef]
    arg_names: list[str]
    return_type: TypeRef
```

Implement `MethodRegistry.methods_for(owner_type)` by unifying each signature owner, resolving its argument and return patterns, and skipping unresolved signatures. Register the requested parameter names (`start`, `length`, `format`, `oldSubstring`, `newSubstring`, `days`, `dateFormat`, `k`) in built-ins.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run: `python -m pytest tests/test_type_system.py -v`

Expected: all type-system tests pass.

- [ ] **Step 5: Commit**

```powershell
git add agent/expression_generation/type_system.py tests/test_type_system.py
git commit -m "feat: enumerate registered fields and methods"
```

### Task 2: Typed context models and recursive builder

**Files:**
- Create: `agent/expression_generation/typed_context.py`
- Create: `tests/test_typed_expression_context.py`

- [ ] **Step 1: Write failing context and NamingSQL tests**

Construct minimal in-memory `LoadedResource` and `FilteredEnvironment` fixtures. Test that:

```python
context = builder.build(build_input)
assert context.root_values[0].expr == "$ctx$.address"
assert any(field.access == "$ctx$.address.addr1" for field in context.root_values[0].fields)
assert "length(): basic.int" in context.root_values[0].fields[0].methods
```

Add a selected NamingSQL candidate owned by `BB_BILL_CHARGE`; assert the template uses `var_name == "it"`, exposes `it.CHARGE_AMT`, and includes `long2str(): basic.String`. Add a missing-return-type case and assert a warning is emitted without a fabricated typed root.

- [ ] **Step 2: Run builder tests and observe RED**

Run: `python -m pytest tests/test_typed_expression_context.py -v`

Expected: collection fails because `agent.expression_generation.typed_context` does not exist.

- [ ] **Step 3: Define the Pydantic output contract**

Create `TypedAccessView`, `TypedRootValue`, `TypedVarTemplate`, `TypedMethodView`, `TypedExpressionPattern`, `TypedExpressionContext`, and `TypedExpressionContextBuildInput`. Configure arbitrary input types for `FilteredEnvironment`, `LoadedResource`, `TypeRegistry`, and `MethodRegistry`. Keep `max_items=80`; do not add `max_depth`.

- [ ] **Step 4: Implement resource lookup and BO registration**

Resolve selected contexts, local contexts, functions, BOs, and NamingSQL candidates against `LoadedResource`. Normalize every available return type. Register each selected/owning BO as `TypeDef(owner_type=TypeRef(kind="bo", name=bo.bo_name), fields=...)`. Skip unusable types with stable warnings.

- [ ] **Step 5: Implement expansion to basic leaves**

Recursively expand object fields from `TypeRegistry.resolve_fields`. For lists, attach instantiated List methods and recurse through `first()`; for maps, attach Map methods and recurse through `get(...)`. Stop at basic/void/unknown, on a current-path type cycle, or when the shared `max_items` counter is exhausted. Rank fields by query token match, then node-name match, then annotation match, with stable source-order/name tie-breaks.

- [ ] **Step 6: Implement `it` templates and concrete method catalog**

For every selected NamingSQL, use `var_name="it"` and the owning BO type. Populate `available_fields` from `it.<FIELD>`. Build binding patterns only from fields on that BO and selected context roots; emit warnings for unbound parameters. Deduplicate method catalog entries by rendered owner type and signature and include only methods encountered during emitted expansion.

- [ ] **Step 7: Run builder tests and observe GREEN**

Run: `python -m pytest tests/test_typed_expression_context.py -v`

Expected: all builder tests pass.

- [ ] **Step 8: Commit**

```powershell
git add agent/expression_generation/typed_context.py tests/test_typed_expression_context.py
git commit -m "feat: build typed expression context"
```

### Task 3: List expansion, full-depth traversal, and item budget

**Files:**
- Modify: `tests/test_typed_expression_context.py`
- Modify: `agent/expression_generation/typed_context.py`

- [ ] **Step 1: Write failing collection and truncation tests**

Add a root with `List<bo.BB_BILL_CHARGE>` and assert root methods include `first`, `find{expr}`, `findAll{expr}`, and `size`, while fields include `first().CHARGE_AMT`. Add nested logic types deeper than four levels and assert the final basic leaf is emitted. Add cyclic types and assert traversal terminates with a warning. Build with a small `max_items` and assert the total counted output does not exceed it and repeated builds are identical.

- [ ] **Step 2: Run the new cases and observe RED**

Run: `python -m pytest tests/test_typed_expression_context.py -v`

Expected: one or more new assertions fail for list traversal, deep traversal, cycle handling, or global budgeting.

- [ ] **Step 3: Complete traversal and shared-budget behavior**

Adjust the builder so list/map access segments are rendered as `first()` / `get(...)`, traversal has no numeric depth cutoff, cycle keys are removed when unwinding sibling branches, and every appended root/template/access/method-group/pattern consumes exactly one shared budget item.

- [ ] **Step 4: Run builder and type-system tests**

Run: `python -m pytest tests/test_typed_expression_context.py tests/test_type_system.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add agent/expression_generation/typed_context.py tests/test_typed_expression_context.py
git commit -m "feat: bound typed context expansion"
```

### Task 4: Planner prompt and value-logic integration

**Files:**
- Modify: `agent/planner/llm_planner.py`
- Modify: `agent/value_logic_generator.py`
- Modify: `prompt.json`
- Modify: `tests/test_llm_planner.py`
- Modify: `tests/test_value_logic_generator.py`

- [ ] **Step 1: Write failing prompt-boundary tests**

Capture the planner client request and assert a supplied `TypedExpressionContext` appears in a `typed_context_json` prompt argument with Root Values, Suggested Vars, Available Methods by Type, and Expression Patterns. Assert the planner response still validates to the existing `Plan`. Add a generator test using a fake builder and planner; assert the builder receives filtered and loaded resources and the planner receives the same typed context.

- [ ] **Step 2: Run integration tests and observe RED**

Run: `python -m pytest tests/test_llm_planner.py tests/test_value_logic_generator.py -v`

Expected: FAIL because planner and generator do not accept typed context dependencies or arguments.

- [ ] **Step 3: Add optional planner input and bounded serialization**

Add `typed_context: TypedExpressionContext | None = None` to `LLMPlanner.plan`. Serialize a bounded prompt view into `typed_context_json`, pass it to both normal and repair prompt calls, and keep the existing `Plan` schema and validation unchanged. Update both prompt templates with the four named typed-context blocks.

- [ ] **Step 4: Wire the builder after filtering**

Allow `ValueLogicGenerator` to receive optional type registry, method registry, and typed-context builder dependencies. After filtering and NamingSQL selection, call the builder with `TypedExpressionContextBuildInput`, then pass the result to `llm_planner.plan(..., typed_context=typed_context)`. Do not modify ASTBuilder, validator, renderer, or planner models.

- [ ] **Step 5: Run integration tests and observe GREEN**

Run: `python -m pytest tests/test_llm_planner.py tests/test_value_logic_generator.py -v`

Expected: all affected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add agent/planner/llm_planner.py agent/value_logic_generator.py prompt.json tests/test_llm_planner.py tests/test_value_logic_generator.py
git commit -m "feat: pass typed context to expression planner"
```

### Task 5: Verification and scope audit

**Files:**
- Verify only: all files changed by Tasks 1-4

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_type_system.py tests/test_typed_expression_context.py tests/test_llm_planner.py tests/test_value_logic_generator.py -q`

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete suite and compare with baseline**

Run: `python -m pytest -q`

Expected: no failures beyond the previously recorded 17 missing-sample-data baseline failures; pass count increases by the number of new tests.

- [ ] **Step 3: Audit forbidden files and output schema**

Run: `git diff --name-only 80aa8ab..HEAD` and `git diff --check 80aa8ab..HEAD`.

Expected: no AST builder, validator, renderer, or planner model file is changed, and no whitespace errors are reported.
