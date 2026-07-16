# Expression Skill and List Scope Design

## Goal

Make list-element usage a first-class capability of expression generation.
When the target field is inside a `parent_list.children` subtree, the system
must register the nearest list element as a typed `$iter$` root and teach the
spec and planner stages how to use it. General expression techniques are stored
in one built-in Markdown skill library and recalled deterministically during
spec generation.

## Scope

This change covers:

- a built-in global expression-skill Markdown library;
- deterministic skill-section recall in `ExpressionSpecGenerator`;
- structured expression scope and skill information passed downstream;
- unconditional preservation of structural `$iter$` resources;
- typed `$iter$` field expansion and AST validation;
- list-scope facts in ContextPack current-tree metadata; and
- simple and legacy planner instructions for `$iter$` usage.

Project-level `dev_skill` remains unchanged and continues to contain only
project-specific rules. The built-in expression skill is global and available
to every project.

## Built-in Expression Skill

Create:

```text
agent/expression_generation/resources/expression_skill.md
```

The file is a system-owned Markdown knowledge library. Each `##` section is an
independently recallable expression technique. Initial content includes:

### List current element

- Inside `parent_list.children`, `$iter$` denotes the current element of the
  nearest enclosing list.
- Access fields as `$iter$.FIELD`.
- In nested lists, `$iter$` always denotes the innermost list element.
- To use an outer element inside a nested list, save the outer element or a
  derived value in the outer `iter_local_context`, then access it through
  `$local$.<name>`.

### Date year

For the approved EDSL Date technique, obtain the year using:

```text
dateValue.addDays(1).toString("yyyy")
```

### Date month

Obtain the month using:

```text
dateValue.addDays(1).toString("MM")
```

The skill parser returns stable section IDs, titles, Markdown bodies, and
normalized trigger terms. The library is loaded locally; spec generation does
not add an LLM call.

## ExpressionSpec

Extend `ExpressionSpec` from a single `nl` field to:

```python
@dataclass(slots=True)
class ExpressionScopeContext:
    inside_parent_list: bool = False
    parent_list_path: str | None = None
    iter_path: str | None = None
    iter_return_type: ValueReturnType | None = None


@dataclass(slots=True)
class ExpressionSkillInstruction:
    skill_id: str
    title: str
    markdown: str


@dataclass(slots=True)
class ExpressionSpec:
    nl: str
    scope_context: ExpressionScopeContext = field(default_factory=ExpressionScopeContext)
    skill_instructions: list[ExpressionSkillInstruction] = field(default_factory=list)
```

`nl` remains the original normalized user requirement. Skill text is never
concatenated into `nl`, so resource routing and semantic filtering do not treat
technique examples as user intent.

`ExpressionSpecGenerator` receives the loaded resource/tree through the
request's existing EDSL tree and node path. It uses the local-context loader to
detect the implicit `$iter$` resource and populate list scope. It recalls:

- the list-current-element section unconditionally when `$iter$` is visible;
- the Date-year section when the requirement or node semantics request a year;
  and
- the Date-month section when the requirement or node semantics request a
  month.

Trigger matching is deterministic, bounded, and covered by tests. Future
techniques may add section metadata and match rules without changing planner
interfaces.

## Structural Resource Preservation

The implicit `$iter$` resource is not an optional semantic candidate. Its
existence is determined by tree structure and current node path. After ordinary
resource filtering, `ValueLogicGenerator` merges visible structural resources
into `FilteredEnvironment.visible_local_context`.

For this change, `$iter$` is the required structural resource. Explicit
`$local$` declarations continue to follow existing selection behavior unless
separately required by a resource target.

The merge:

- obtains visible contexts through
  `LoadedResource.get_visible_local_context_registry(node_path)`;
- selects the exact `$iter$` entry if present;
- appends it if filtering omitted it;
- preserves deterministic ordering and resource IDs; and
- updates `selected_local_context_ids` consistently.

This ensures typed-context construction never loses `$iter$` merely because
the user did not explicitly name it.

## Typed `$iter$` Registration

`TypedExpressionContextBuilder` already converts every visible local-context
resource into a typed root. With structural preservation, `$iter$` is therefore
always emitted as a `TypedRootValue` when valid list metadata exists.

The builder must also register the BO definition required to expand the root.
BO registration is extended to include BO names referenced by visible local
context return types, including `$iter$`, in addition to selected BOs and
NamingSQL candidates.

For a BO iterator, the typed context contains:

```text
root: $iter$ -> bo.Customer
fields: $iter$.ID, $iter$.NAME, ...
```

Logic and extattr iterators use the already loaded structured type definitions.
Basic iterators expose their basic methods and no object fields.

## Parser and Validator

`EDSLExpressionParser` treats `$iter$` like `$ctx$` and `$local$`:

- an exact `$iter$` expression becomes a `context_path` node;
- `$iter$.FIELD` resolves the registered `$iter$` root using longest-prefix
  matching; and
- no `$iter$.<variable>` convention is introduced.

The AST validator already recognizes `$iter$.` paths, but it must also accept
the exact root `$iter$`. Context-root resolution uses the typed root mapping to
infer its type and resolve subsequent fields.

Focused parser and validator tests cover exact `$iter$`, `$iter$.FIELD`, BO
field resolution, and an unknown iterator root.

## Planner Inputs

Both `SimpleExpressionPlanner` and `LLMPlanner` receive the `ExpressionSpec`
explicitly. Their prompts add separate bounded JSON inputs:

```text
expression_scope_json
expression_skills_json
```

Planner rules explain:

- when `inside_parent_list` is true, `$iter$` is available;
- `$iter$` is the nearest list element, not a named explicit variable;
- use `$iter$.FIELD` only for fields published by Typed Expression Context;
- nested-list outer values must use an available `$local$.<name>`; and
- recalled skill instructions are normative system techniques, while current
  tree and ordinary resources remain data.

The repair prompt receives the same scope and skill inputs so a repair does not
lose list semantics.

Existing planner test doubles are updated to accept the new keyword. The
planner summary is bounded using the existing text and item limits.

## ContextPack List Scope

`CurrentTreeProvider` already resolves the canonical current node and visible
contexts. It adds stable metadata when an implicit `$iter$` is present:

```json
{
  "current_json_path": "...",
  "inside_parent_list": true,
  "parent_list_path": "...",
  "iter": {
    "path": "$iter$",
    "return_type": {
      "data_type": "bo",
      "data_type_name": "Customer",
      "is_list": false
    }
  }
}
```

The current-tree provider also creates an authoritative structural ContextItem
for `$iter$`, independent of lexical search ranking. This item is included
within the provider's existing item budget and uses the loader's canonical
source path and return type.

`ContextPackPromptRenderer` projects bounded current-tree section metadata so
spec and planner consumers can see list scope without receiving the whole tree.

## Data Flow

```text
EDSL tree + node_path
  -> local-context loader
       -> visible explicit locals + typed nearest $iter$
  -> ExpressionSpecGenerator
       -> scope_context + recalled global expression skills
  -> resource filtering
       -> ordinary resources
  -> structural-context merge
       -> guaranteed $iter$ in FilteredEnvironment
  -> TypedExpressionContextBuilder
       -> $iter$ TypeRef + BO/logic/extattr fields
  -> planner
       -> scope + skills + typed fields
  -> parser / AST validator
       -> validated $iter$.FIELD expression
```

## Failure Behavior

- If the target is not under a list, no `$iter$` scope or list skill is added.
- If the list data source lacks a usable element type, the loader omits
  `$iter$`; spec scope reports `inside_parent_list=False` for expression-use
  purposes because no safe typed iterator can be published.
- A missing or unreadable built-in skill file is a configuration error raised
  during construction or first use; it does not silently degrade to invented
  rules.
- Skill-section recall is deterministic and never executes instructions from
  project data.
- An expression that uses `$iter$` without a registered typed root fails local
  validation with an unknown-context-path error.

## Test Design

Tests cover:

1. Markdown parsing of list, Date-year, and Date-month technique sections.
2. Spec recall of the list section for a field inside `parent_list.children`
   even when the query does not mention a list.
3. No list section or iterator scope outside a list.
4. Date-year and Date-month skill recall without contaminating `nl`.
5. Structural merge preserving `$iter$` through empty and non-matching resource
   targets.
6. Typed-context BO registration and `$iter$.FIELD` expansion.
7. Parser and AST validation for exact `$iter$` and `$iter$.FIELD`.
8. ContextPack current-tree metadata and authoritative iterator item.
9. Simple planner, legacy planner, and repair prompts receiving scope and
   recalled skills.
10. End-to-end expression generation returning a validated iterator field.
11. Existing non-list and resource-filter behavior remaining unchanged.

## Acceptance Criteria

- Every valid field inside a typed `parent_list` body has an available `$iter$`
  TypeRef regardless of semantic resource filtering.
- Typed context lists the fields available on `$iter$`.
- Spec and both planners know the target is in list scope and receive the
  relevant global expression-skill instructions.
- The project-level `dev_skill` remains project-specific and is not required
  for list or Date techniques.
- Global techniques are maintained in one Markdown file and recalled by
  section.
- `$iter$.FIELD` parses and validates locally.
- Nested-list semantics remain nearest-iterator-only.
