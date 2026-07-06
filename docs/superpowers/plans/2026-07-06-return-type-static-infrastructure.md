# Return Type Static Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build standalone return-type normalization plus object-field and built-in-method registries without integrating them into expression generation.

**Architecture:** Add one isolated `type_system.py` module containing Pydantic type/signature models and in-memory registries. Drive each behavior through a focused pytest module; keep registration explicit and leave planner, validator, renderer, and AST flow untouched.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest

---

### Task 1: TypeRef and return-type normalization

**Files:**
- Create: `agent/expression_generation/type_system.py`
- Create: `tests/test_type_system.py`

- [ ] **Step 1: Write failing normalization tests**

Add parametrized tests that import `TypeRef` and `normalize_return_type`, pass dictionaries for all six required scalar/list examples, and compare against explicit `TypeRef` instances. Add one test using the existing `ReturnType` Pydantic model and one test asserting `None` becomes `TypeRef(kind="unknown")`.

- [ ] **Step 2: Verify the tests fail for the missing module**

Run: `pytest tests/test_type_system.py -v`

Expected: collection fails with `ModuleNotFoundError` for `agent.expression_generation.type_system`.

- [ ] **Step 3: Implement TypeRef and normalization**

Define:

```python
class TypeRef(BaseModel):
    kind: Literal["basic", "bo", "logic", "extattr", "list", "map", "void", "unknown"]
    name: str | None = None
    element_type: "TypeRef | None" = None
    key_type: "TypeRef | None" = None
    value_type: "TypeRef | None" = None
    nullable: bool = True
```

Use `model_rebuild()` for recursive fields. In `normalize_return_type`, read fields from either `Mapping` or attributes, normalize enum categories through `.value`, return `unknown` for unusable input, recognize `void`, construct named scalar types for the four supported categories, and wrap the scalar in `TypeRef(kind="list", element_type=scalar)` when `is_list` is true.

- [ ] **Step 4: Verify normalization tests pass**

Run: `pytest tests/test_type_system.py -v`

Expected: all normalization tests pass.

- [ ] **Step 5: Commit the normalization slice**

```powershell
git add agent/expression_generation/type_system.py tests/test_type_system.py
git commit -m "feat: normalize resource return types"
```

### Task 2: Object type and field registry

**Files:**
- Modify: `agent/expression_generation/type_system.py`
- Modify: `tests/test_type_system.py`

- [ ] **Step 1: Write a failing BO field resolution test**

Create `TypeDef(owner_type=TypeRef(kind="bo", name="BB_BILL_CHARGE"), fields={"CHARGE_AMT": TypeRef(kind="basic", name="decimal")})`, register it, and assert `resolve_field` returns the decimal type. Also assert an unknown field returns `None`.

- [ ] **Step 2: Verify failure is caused by missing registry models**

Run: `pytest tests/test_type_system.py::test_type_registry_resolves_registered_bo_field -v`

Expected: FAIL because `TypeDef` or `TypeRegistry` is not defined.

- [ ] **Step 3: Implement TypeDef and TypeRegistry**

Add a Pydantic `TypeDef` with `owner_type: TypeRef` and `fields: dict[str, TypeRef]`. Implement `TypeRegistry` with an internal dictionary keyed by a deterministic recursive tuple representation of `TypeRef`; `register_type` replaces the owner entry and `resolve_field` returns the field type or `None`.

- [ ] **Step 4: Verify registry tests pass**

Run: `pytest tests/test_type_system.py -v`

Expected: all current tests pass.

- [ ] **Step 5: Commit the field registry slice**

```powershell
git add agent/expression_generation/type_system.py tests/test_type_system.py
git commit -m "feat: add object type registry"
```

### Task 3: Method signatures, generic matching, and built-ins

**Files:**
- Modify: `agent/expression_generation/type_system.py`
- Modify: `tests/test_type_system.py`

- [ ] **Step 1: Write failing basic and generic method tests**

Add tests that create a registry through `create_builtin_method_registry()` and assert:

```python
assert registry.match(STRING, "length", []) == INT
assert registry.match(STRING, "dateValue", [STRING]) == DATE
assert registry.match(list_of(CHARGE), "first", []) == CHARGE
assert registry.match(list_of(CHARGE), "find{expr}", []) == CHARGE
assert registry.match(map_of(STRING, CHARGE), "get", [STRING]) == CHARGE
```

Also assert an argument mismatch and unknown method return `None`, and cover the remaining requested signatures: `substr`, `replace`, `addDays`, `toString`, `int2str`, `long2str`, `size`, and `findAll{expr}`.

- [ ] **Step 2: Verify failure is caused by missing method infrastructure**

Run: `pytest tests/test_type_system.py -v`

Expected: FAIL because method signature or registry APIs are missing.

- [ ] **Step 3: Implement method patterns and matching**

Add a private recursive `TypePattern` Pydantic model whose kinds mirror `TypeRef` plus `var`; it carries the same nested fields and uses `name` for a type-variable name. Add `MethodSig(owner_type: TypePattern, name: str, arg_types: list[TypePattern], return_type: TypePattern)`. Provide a small conversion helper for concrete `TypeRef` patterns. Implement `MethodRegistry.register_method` and `match`: filter by name and arity, recursively unify owner and arguments while maintaining consistent `var` bindings, then recursively substitute bindings into the return pattern as a concrete `TypeRef`. Return the first match or `None`.

- [ ] **Step 4: Register exactly the requested built-ins**

Implement `create_builtin_method_registry()` with explicit registrations for String, Date, int, long, `List<T>`, and `Map<String,T>`. Treat `find{expr}` and `findAll{expr}` as literal zero-argument method names in this phase.

- [ ] **Step 5: Verify method tests pass**

Run: `pytest tests/test_type_system.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit the method registry slice**

```powershell
git add agent/expression_generation/type_system.py tests/test_type_system.py
git commit -m "feat: add built-in method type registry"
```

### Task 4: Scope and regression verification

**Files:**
- Verify only: `agent/expression_generation/type_system.py`
- Verify only: `tests/test_type_system.py`

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_type_system.py -v`

Expected: all return-type infrastructure tests pass without warnings.

- [ ] **Step 2: Run the complete suite**

Run: `pytest -q`

Expected: the existing suite and new tests pass.

- [ ] **Step 3: Verify forbidden areas are untouched**

Run: `git diff --name-only HEAD~3..HEAD`

Expected: only the type-system module, its tests, and approved design/plan documents appear; no planner, validator, renderer, or expression-generation main-flow file appears.

- [ ] **Step 4: Inspect final diff quality**

Run: `git diff --check HEAD~3..HEAD`

Expected: no whitespace errors.
