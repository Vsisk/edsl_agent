# Parent List Context Loader Design

## Goal

Extend the existing local-context loader so it projects the resources that are
available at a target EDSL tree path with the correct `parent_list` loop scope.
The loader remains a read-only resource projection layer. It does not generate
tree content or validate authoring-time constraints.

## Scope

This change is limited to `load_visible_local_context_registry(edsl_tree,
node_path)` and the directly related resource projection and tests.

The loader will expose:

- `local_context` declarations as `$local$.<property_name>`;
- `iter_local_context` declarations as `$local$.<property_name>` when the
  target is inside the declaring list's loop body; and
- one implicit `$iter$` resource for the nearest enclosing `parent_list` loop.

The loader will not:

- generate or complete a `parent_list.data_source`;
- validate that a data source returns a list;
- validate duplicate variable names on a tree branch;
- implement variable shadowing;
- modify node-generation behavior; or
- take over expression-generation responsibilities.

## Resource Model

The existing `LocalContextRegistry` remains the output type. No new registry
model is required.

| Source | `context_name` | Visibility | `property_type` |
| --- | --- | --- | --- |
| `local_context` | `$local$.<name>` | Declaring node and its descendants | `local` |
| `iter_local_context` | `$local$.<name>` | Inside the declaring `parent_list.children` subtree | `iter` |
| Nearest list element | `$iter$` | Inside the declaring `parent_list.children` subtree | `iter` |

`property_type="iter"` records that a resource is loop-scoped; it no longer
selects the `$iter$` call prefix. Explicit variables always use `$local$`.

The implicit `$iter$` resource uses a deterministic resource ID in the same
ordered result set and a source path pointing to the enclosing list's
`data_source`. Its annotation and tags are derived from the enclosing list and
the resolved element type using the loader's existing tag conventions.

## Scope Resolution

The loader continues to resolve the existing nodes along `node_path`, ordered
from the mapping root toward the target. For each resolved `parent` or
`parent_list`, it loads that node's `local_context` entries.

An enclosing `parent_list` contributes loop-scoped resources only when the
target path is within that list's `children` subtree. Merely targeting the
`parent_list` node itself, its `data_source`, or another property on the list
does not enter its loop body and therefore does not expose that list's
`iter_local_context` or `$iter$`.

For a target inside nested list bodies:

- local variables from all applicable ancestor scopes remain visible;
- loop-local variables from every list body already entered remain visible as
  `$local$.<name>`; and
- only the nearest enclosing list contributes `$iter$`.

The outer `$iter$` is therefore unavailable inside a nested list. A tree author
who needs it must first save the outer element or a derived value in the outer
list's `iter_local_context`; the nested list then reads that value through
`$local$.<name>`.

The loader preserves declarations as loaded resources and does not resolve or
reject duplicate names. Branch-level uniqueness belongs to tree authoring or
validation, outside this change.

## `$iter$` Element Type

The implicit `$iter$` represents one element, never the list container. Its
`return_type.is_list` is therefore `False`.

### SQL data source

For `data_source.data_source_type == "sql"`, the element type is obtained from:

```text
data_source.sql_query.bo_name
```

The loader emits:

```text
ReturnType(data_type="bo", data_type_name=<bo_name>, is_list=False)
```

No BO definition lookup is required merely to publish the typed root. Existing
downstream type infrastructure can expand the BO fields when that BO is present
in the loaded BO registry.

### Expression data source

For `data_source.data_source_type == "expression"`, the loader reads:

```text
data_source.data_expression.return_type
```

It copies `data_type` and `data_type_name` and normalizes `is_list` to `False`
for the current element.

The loader does not assert that the source metadata originally had
`is_list=True`. It treats the existing metadata as an input resource and only
projects the element view.

### Missing metadata

If the loader cannot determine an element type because the SQL BO name or
expression return type is missing or structurally unreadable, it omits `$iter$`
for that list. It still returns every readable local-context resource. Resource
loading remains tolerant of partially authored trees.

## Integration Effects

Consumers that obtain visible context through `ResourceLoader` or
`EdslProjectContextResolver` will receive the corrected call names and scope.
The resolver may continue to separate records using `property_type`:

- declarations from `iter_local_context` remain categorized as loop-scoped;
- their `context_name` is nevertheless `$local$.<name>`; and
- the implicit element is represented by the exact context name `$iter$`.

Any downstream asset categorization that currently assumes every
`property_type="iter"` resource starts with `$iter$.` must use the property type
only as scope metadata, not as syntax reconstruction.

## Failure Behavior

Existing invalid-path behavior remains unchanged. Malformed individual context
entries are skipped consistently with the current loader.

Missing or incomplete list data-source type metadata is not a loader error. It
only prevents creation of the implicit `$iter$` resource for that list.

## Test Design

Focused loader tests will cover:

1. `iter_local_context` is exposed as `$local$.<name>` while retaining
   `property_type="iter"`.
2. A target at the `parent_list` node sees its `local_context` but not its
   `iter_local_context` or `$iter$`.
3. A target inside `parent_list.children` sees both explicit context groups and
   the implicit `$iter$`.
4. A SQL list data source produces `$iter$` with the declared BO element type.
5. An expression list data source reads
   `data_source.data_expression.return_type` and produces a non-list element
   type.
6. Nested list bodies expose only the innermost `$iter$` while preserving outer
   loop-local values as `$local$.<name>`.
7. Missing element-type metadata omits `$iter$` without losing other context
   resources.
8. Existing insert-position and ordinary parent visibility behavior remains
   compatible.

Integration assertions in resource-loader and context-resolver tests will be
updated where they currently expect `$iter$.<explicit_name>`.

## Acceptance Criteria

- Both explicit local-context collections use the `$local$` call prefix.
- `iter_local_context` is visible only after entering its declaring list's
  `children` subtree.
- `$iter$` denotes the nearest enclosing list element and has a usable element
  return type when existing data-source metadata provides one.
- Nested lists do not expose an outer `$iter$`.
- Partial tree metadata does not prevent other visible resources from loading.
- No generation-time or duplicate-name validation is added to the loader.
