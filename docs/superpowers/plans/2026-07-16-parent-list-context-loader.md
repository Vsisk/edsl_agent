# Parent List Context Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing local-context loader expose correctly scoped `$local$` declarations and the nearest enclosing list element as `$iter$`.

**Architecture:** Keep all tree-path and list-scope projection inside `agent/resource_manager/loader/local_context_loader.py`. The loader will distinguish declarations that are always visible from declarations visible only after entering a `parent_list.children` subtree, track the nearest entered list, and derive its element type from existing SQL or expression data-source metadata. Existing registry, resource-loader, and context-resolver interfaces remain unchanged.

**Tech Stack:** Python 3.12, Pydantic 2 models, `jsonpath-ng`, pytest/unittest-compatible tests.

---

### Task 1: Correct explicit loop-local visibility and syntax

**Files:**
- Modify: `tests/test_resource_loader.py`
- Modify: `agent/resource_manager/loader/local_context_loader.py`

- [ ] **Step 1: Write failing tests for list-node and list-body visibility**

Update the existing resource-loader assertions and add a focused body-scope test. The target list node must expose its normal local context but not its own loop-local declarations. A target under `children` must expose the loop-local declaration using `$local$` while retaining `property_type="iter"`.

```python
def test_load_visible_local_context_registry_for_existing_node_path(self):
    registry = load_visible_local_context_registry(
        sample_edsl_tree_payload(),
        "$.mapping_content.children[1]",
    )

    self.assertEqual(
        [item.context_name for item in registry],
        ["$local$.rootLocal", "$local$.local_2"],
    )


def test_load_visible_local_context_registry_for_insert_position(self):
    registry = load_visible_local_context_registry(
        sample_edsl_tree_payload(),
        "$.mapping_content.children[1].children[0]",
    )

    self.assertEqual(
        [item.context_name for item in registry],
        ["$local$.rootLocal", "$local$.local_2", "$local$.subId"],
    )
    self.assertEqual(registry[-1].property_type, "iter")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
pytest tests/test_resource_loader.py::ResourceLoaderTest::test_load_visible_local_context_registry_for_existing_node_path tests/test_resource_loader.py::ResourceLoaderTest::test_load_visible_local_context_registry_for_insert_position -v
```

Expected: both tests fail because the current loader always exposes `iter_local_context` and formats it as `$iter$.subId`.

- [ ] **Step 3: Implement minimal explicit-context scope handling**

Replace the prefix-bearing field table with declaration metadata and only load `iter_local_context` after the target enters the declaring list's `children` path.

```python
LOCAL_CONTEXT_FIELDS = (
    ("local_context", "local"),
    ("lobal_context", "local"),
)


def _is_inside_list_body(node_path: str, list_path: str) -> bool:
    body_path = f"{list_path}.children"
    return node_path == body_path or node_path.startswith(
        (f"{body_path}[", f"{body_path}.")
    )
```

Normalize `node_path` once, load the ordinary local fields for every resolved parent node, and add `("iter_local_context", "iter")` only when `_is_inside_list_body(...)` is true. Construct every explicit declaration name as `f"$local$.{property_name}"`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2.

Expected: both tests pass.

- [ ] **Step 5: Commit explicit scope behavior**

```powershell
git add -- agent/resource_manager/loader/local_context_loader.py tests/test_resource_loader.py
git commit -m "fix: scope explicit parent list contexts"
```

### Task 2: Load the nearest typed `$iter$` resource

**Files:**
- Modify: `tests/test_resource_loader.py`
- Modify: `agent/resource_manager/loader/local_context_loader.py`

- [ ] **Step 1: Add failing SQL, expression, and nested tests**

Add a child leaf and data source to independent list fixtures, then assert that the body receives one exact `$iter$` resource.

```python
def test_list_body_loads_sql_data_source_element_as_iter(self):
    tree = sample_edsl_tree_payload()
    parent_list = tree["mapping_content"]["children"][1]
    parent_list["children"] = [{"tree_node_type": "simple_leaf"}]
    parent_list["data_source"] = {
        "data_source_type": "sql",
        "sql_query": {"bo_name": "SUBSCRIBER"},
    }

    registry = load_visible_local_context_registry(
        tree, "$.mapping_content.children[1].children[0]"
    )
    current = next(item for item in registry if item.context_name == "$iter$")

    self.assertEqual(current.property_type, "iter")
    self.assertEqual(current.source_path, "$.mapping_content.children[1].data_source")
    self.assertEqual(current.return_type.data_type, "bo")
    self.assertEqual(current.return_type.data_type_name, "SUBSCRIBER")
    self.assertFalse(current.return_type.is_list)


def test_list_body_loads_expression_return_element_as_iter(self):
    tree = sample_edsl_tree_payload()
    parent_list = tree["mapping_content"]["children"][1]
    parent_list["children"] = [{"tree_node_type": "simple_leaf"}]
    parent_list["data_source"] = {
        "data_source_type": "expression",
        "data_expression": {
            "expression": "$local$.items",
            "return_type": {
                "data_type": "logic",
                "data_type_name": "SubscriberView",
                "is_list": True,
            },
        },
    }

    registry = load_visible_local_context_registry(
        tree, "$.mapping_content.children[1].children[0]"
    )
    current = next(item for item in registry if item.context_name == "$iter$")

    self.assertEqual(current.return_type.data_type, "logic")
    self.assertEqual(current.return_type.data_type_name, "SubscriberView")
    self.assertFalse(current.return_type.is_list)


def test_nested_list_body_loads_only_nearest_iter(self):
    tree = {
        "mapping_content": {
            "tree_node_type": "parent_list",
            "data_source": {
                "data_source_type": "sql",
                "sql_query": {"bo_name": "OuterItem"},
            },
            "iter_local_context": [
                {
                    "property_name": "outerItem",
                    "return_type": {
                        "data_type": "bo",
                        "data_type_name": "OuterItem",
                        "is_list": False,
                    },
                }
            ],
            "children": [
                {
                    "tree_node_type": "parent_list",
                    "data_source": {
                        "data_source_type": "expression",
                        "data_expression": {
                            "return_type": {
                                "data_type": "logic",
                                "data_type_name": "InnerItem",
                                "is_list": True,
                            }
                        },
                    },
                    "children": [{"tree_node_type": "simple_leaf"}],
                }
            ],
        }
    }
    registry = load_visible_local_context_registry(
        tree, "$.mapping_content.children[0].children[0]"
    )
    names = [item.context_name for item in registry]
    by_name = {item.context_name: item for item in registry}

    self.assertIn("$local$.outerItem", names)
    self.assertEqual(names.count("$iter$"), 1)
    self.assertEqual(by_name["$iter$"].return_type.data_type_name, "InnerItem")
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
pytest tests/test_resource_loader.py -k "list_body_loads_sql or list_body_loads_expression or nested_list_body" -v
```

Expected: all three tests fail because no `$iter$` resource exists. The Task 1
insert-position test already covers a list body with missing element metadata:
it must retain `$local$.subId` while omitting `$iter$`.

- [ ] **Step 3: Implement element return-type projection**

Add a helper that reads only existing metadata and returns `None` when it is incomplete.

```python
def _list_element_return_type(node: Dict[str, Any]) -> Dict[str, Any] | None:
    data_source = node.get("data_source")
    if not isinstance(data_source, dict):
        return None
    source_type = str(data_source.get("data_source_type") or "").strip().lower()
    if source_type == "sql":
        sql_query = data_source.get("sql_query")
        if not isinstance(sql_query, dict):
            return None
        bo_name = str(sql_query.get("bo_name") or "").strip()
        if not bo_name:
            return None
        return {"data_type": "bo", "data_type_name": bo_name, "is_list": False}
    if source_type == "expression":
        expression = data_source.get("data_expression")
        raw = expression.get("return_type") if isinstance(expression, dict) else None
        if not isinstance(raw, dict) or not str(raw.get("data_type") or "").strip():
            return None
        return {
            "data_type": raw["data_type"],
            "data_type_name": raw.get("data_type_name"),
            "is_list": False,
        }
    return None
```

Track the nearest entered `parent_list` during the ancestor walk, overwriting
the candidate when a deeper entered list is encountered. After explicit
declarations are loaded, append one `LocalContextRegistry` with
`context_name="$iter$"`, `property_type="iter"`,
`source_path=f"{list_path}.data_source"`, and the projected element return
type. Never return early when the type is absent. Reuse `build_tags` for the
list XML name, annotation, `$iter$`, and concrete type name.

- [ ] **Step 4: Run the new tests and verify GREEN**

Run the command from Step 2.

Expected: all three tests pass.

- [ ] **Step 5: Commit typed current-element loading**

```powershell
git add -- agent/resource_manager/loader/local_context_loader.py tests/test_resource_loader.py
git commit -m "feat: load typed parent list iterator resource"
```

### Task 3: Run the complete resource-loader regression file

**Files:**
- Verify: `tests/test_resource_loader.py`
- Modify: `agent/resource_manager/loader/local_context_loader.py` only when an existing regression exposes a behavior conflict

- [ ] **Step 1: Run all resource-loader tests**

Run:

```powershell
pytest tests/test_resource_loader.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Fix only regressions caused by the new scope rules**

If an existing assertion encodes the old `$iter$.<explicit_name>` syntax or
list-node visibility, update that assertion. If production behavior unrelated
to the approved design fails, preserve it and make the smallest loader
correction.

- [ ] **Step 3: Re-run all resource-loader tests**

Run the command from Step 1.

Expected: all tests pass.

- [ ] **Step 4: Commit resource-loader regression coverage**

```powershell
git add -- agent/resource_manager/loader/local_context_loader.py tests/test_resource_loader.py
git commit -m "test: cover nested parent list context loading"
```

### Task 4: Update loader consumers and regression expectations

**Files:**
- Modify: `tests/test_context_resolvers.py`
- Modify: `tests/test_environment.py`
- Modify: `tests/test_context_asset_builder.py` if its fixture represents an explicit `iter_local_context` declaration
- Modify: other tests containing obsolete `$iter$.<explicit_name>` expectations

- [ ] **Step 1: Update integration fixtures and assertions to the new resource syntax**

Replace expectations for explicit declarations such as `$iter$.subId` and `$iter$.line` with `$local$.subId` and `$local$.line`. Keep `$iter$` only for fixtures representing an implicit current list element. Where a resolver target is the list node itself, remove expectations that its own `iter_local_context` is visible; where the test needs loop scope, target a child path.

- [ ] **Step 2: Run affected consumer tests**

Run:

```powershell
pytest tests/test_context_resolvers.py tests/test_environment.py tests/test_context_asset_builder.py tests/test_typed_expression_context.py -v
```

Expected: all affected consumer tests pass with explicit loop-local variables represented as `$local$` resources.

- [ ] **Step 3: Search for stale explicit iterator syntax**

Run:

```powershell
rg -n -S '\$iter\$\.[A-Za-z_]' agent tests
```

Expected: no loader-produced explicit context expectation remains. Any surviving occurrence must be inspected and retained only if it intentionally models legacy input rather than `iter_local_context` output.

- [ ] **Step 4: Commit consumer expectation updates**

```powershell
git add -- tests
git commit -m "test: align consumers with loop context resources"
```

### Task 5: Full verification

**Files:**
- Verify: `agent/resource_manager/loader/local_context_loader.py`
- Verify: all modified tests

- [ ] **Step 1: Run formatting and whitespace validation**

Run:

```powershell
git diff --check
```

Expected: exit code 0 with no whitespace errors.

- [ ] **Step 2: Run the complete test suite**

Run:

```powershell
pytest -q
```

Expected: exit code 0 with no failed tests.

- [ ] **Step 3: Review the implementation against the design acceptance criteria**

Confirm from the diff and test output that explicit variables use `$local$`, loop-only variables require entry into `children`, only the nearest typed `$iter$` is projected, incomplete metadata is tolerated, and no generation or duplicate-name validation was added.

- [ ] **Step 4: Commit any final test-only or documentation alignment**

If Step 3 required changes, run the affected tests again, then commit only those verified changes:

```powershell
git add -- agent/resource_manager/loader/local_context_loader.py tests docs/superpowers/plans/2026-07-16-parent-list-context-loader.md
git commit -m "chore: finalize parent list context loader"
```

### Task 6: Derive explicit declaration types from their data sources

**Files:**
- Modify: `tests/test_resource_loader.py`
- Modify: `agent/resource_manager/loader/local_context_loader.py`
- Update: consumer fixtures that still place authoritative return types at the
  top level of `local_context` or `iter_local_context` entries

- [ ] **Step 1: Write failing tests for SQL, expression, ignored legacy, and default types**

Add focused loader tests showing that SQL declarations become `List<BO>`,
expression declarations preserve their nested return type, conflicting
top-level `return_type` is ignored, and missing metadata becomes
`basic.String` with `is_list=False`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_resource_loader.py -k "local_context_type" -v
```

Expected: assertions fail because the loader currently reads
`context_item.return_type` directly.

- [ ] **Step 3: Implement one declaration return-type helper**

Add `_local_context_return_type(context_item)` that reads
`context_item.data_source`, projects SQL as a BO list, preserves expression
return types, and returns the default basic String type for incomplete input.
Use the helper for both the registry return type and tag construction.

- [ ] **Step 4: Run focused and loader regression tests**

Run:

```powershell
python -m pytest tests/test_resource_loader.py -v
```

Expected: all resource-loader tests pass.

- [ ] **Step 5: Run the complete test suite and merge the verified branch**

Run:

```powershell
git diff --check
python -m pytest -q
```

Expected: exit code 0 with no failed tests.
