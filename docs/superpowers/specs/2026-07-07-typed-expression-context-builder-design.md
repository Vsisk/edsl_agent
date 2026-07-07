# Typed Expression Context Builder Design

## Scope

Build a typed expression context from the resources already selected into `FilteredEnvironment`, then pass that context into the existing LLM planner prompt. The planner output schema remains unchanged. This change does not add an expression parser and does not modify ASTBuilder, AST validation, or rendering.

The repository does not currently contain `ResourceManager.select`, `CandidateSet`, or `NodeInput`. This design therefore uses the existing `filter_resources` / `build_filtered_environment` result and resolves full resource definitions from `LoadedResource`.

## Data Flow

The expression-generation path becomes:

1. Filter resources into `FilteredEnvironment`.
2. Build or enrich `TypeRegistry` from the selected BO definitions.
3. Call `TypedExpressionContextBuilder.build(...)` with the query, `NodeDef`, filtered environment, loaded resources, type registry, and method registry.
4. Call `LLMPlanner.plan(..., typed_context=typed_context)`.
5. Continue validating the unchanged `Plan`, building the AST, validating it, and rendering it as before.

## Input and Output Models

`TypedExpressionContextBuildInput` contains:

- `query: str`
- `node: NodeDef`
- `filtered_env: FilteredEnvironment`
- `loaded_resource: LoadedResource`
- `type_registry: TypeRegistry`
- `method_registry: MethodRegistry`
- `max_depth: int = 4`
- `max_items: int = 80`

`TypedExpressionContext` contains:

- `root_values: list[TypedRootValue]`
- `var_templates: list[TypedVarTemplate]`
- `method_catalog: list[TypedMethodView]`
- `expression_patterns: list[TypedExpressionPattern]`
- `warnings: list[str]`

`TypedAccessView` is a shared nested field view containing an expression/access string, rendered return type, and rendered method signatures. `TypedRootValue` represents a selected context, local context, function, or directly usable resource root and owns recursively expanded field views. `TypedVarTemplate` represents a NamingSQL BO-row variable and owns its available fields. `TypedMethodView` groups only the signatures observed while expanding the current resources by owner type. `TypedExpressionPattern` provides a short pattern name and expression template derived from concrete available resources.

All output models are Pydantic models with list fields using `default_factory=list`.

## Resource Resolution

The builder starts from `FilteredEnvironment.selected_global_contexts`, `visible_local_context`, `selected_bos`, `selected_functions`, and `naming_sql_selection.candidates`.

For every selected item, it resolves the authoritative resource from `LoadedResource` by resource ID, context path, function identity, BO name, or NamingSQL identity as appropriate. It normalizes the resource's `return_type` with `normalize_return_type`. Missing or unusable return-type metadata causes that typed root or template to be skipped and adds a deterministic warning; the builder does not invent a type.

Selected BO property definitions are registered in the supplied `TypeRegistry` as `bo.<BO_NAME>` fields. Property types are normalized from their `data_type`, `data_type_name`, and `is_list` metadata.

## Recursive Expansion

For `bo`, `logic`, and `extattr`, the builder resolves fields through `TypeRegistry` and recurses. Basic terminal fields receive only methods matching that basic owner type.

For `List<T>`, the field/root receives the matching List methods. The builder expands object fields reachable from `first()` so a list of `bo.BB_BILL_CHARGE` exposes `first().CHARGE_AMT`. It also emits the concrete `find{expr}`, `findAll{expr}`, and `size` signatures relevant to that list.

For `Map<X,T>`, the field/root receives matching Map methods. When `T` is an object type, expansion continues through `get(...)` into `T` fields.

Expansion stops when `max_depth` is reached, a recursive type cycle is detected on the current traversal path, or the global output budget is exhausted. `max_items` counts emitted roots, variable templates, access views, method catalog entries, and expression patterns. The builder never exceeds the limit.

## Ranking and Determinism

Resources and fields are scored using case-insensitive token matches against, in order of weight:

1. query text;
2. `node.node_name`;
3. resource or field annotation/description.

Higher scores are expanded first. Original resource order and field name provide stable tie-breaking, so identical input produces identical output and truncation.

## NamingSQL and `it`

Each selected NamingSQL candidate is resolved to its owning `BoRegistry`. Its `TypedVarTemplate.var_name` is always `it`; `it` represents a row of that BO. Available fields therefore use access strings such as `it.CHARGE_AMT` and types from the owning BO's property definitions.

Suggested binding conditions may reference only fields from that owning BO. The builder correlates NamingSQL parameters and context requirement hints with actual BO fields and selected context roots. When a reliable binding cannot be formed, it emits a parameterized expression pattern and a warning instead of inventing a field or context path.

## Method Catalog

`MethodRegistry` gains a read-only lookup that returns matching instantiated method views for a concrete owner type. The builder uses it while traversing roots and fields. `method_catalog` contains only owner types encountered in the emitted context, deduplicated by owner and rendered signature; the complete built-in table is never dumped into the prompt.

Method signature rendering follows forms such as:

- `length(): basic.int`
- `substr(basic.int start, basic.int length): basic.String`
- `long2str(): basic.String`
- `first(): bo.BB_BILL_CHARGE`

## Planner Prompt Integration

`LLMPlanner.plan` accepts an optional `typed_context: TypedExpressionContext | None`. The planner and repair prompt calls receive a bounded JSON serialization of that context. The prompt adds a `Typed Expression Context` section with:

1. Root Values
2. Suggested Vars
3. Available Methods by Type
4. Expression Patterns

Warnings are included as metadata beneath the typed block. Existing callers may omit `typed_context`, preserving compatibility. `Plan` and its JSON schema are not changed.

## Testing

Tests follow red-green-refactor and cover:

1. `$ctx$.address: logic.Address` expands `addr1: basic.String` with String methods.
2. A selected NamingSQL owned by `BB_BILL_CHARGE` produces an `it` template whose `it.CHARGE_AMT` field exposes `long2str()`.
3. `List<bo.BB_BILL_CHARGE>` exposes `first`, `find{expr}`, `findAll{expr}`, and `size`, plus `first().CHARGE_AMT`.
4. `max_depth` and the global `max_items` budget deterministically truncate output.
5. The planner prompt receives and renders all four typed-context blocks while returning the unchanged `Plan` model.
6. Missing return-type metadata produces warnings without fabricating typed entries.

Focused tests verify the builder and planner boundary. Existing ASTBuilder, validator, and renderer tests must remain untouched.

