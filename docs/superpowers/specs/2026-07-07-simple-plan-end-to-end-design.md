# Simple Expression Plan End-to-End Design

## Scope

Connect typed context, `SimpleExpressionPlan`, local type validation, lightweight AST construction, and EDSL rendering into the expression-generation path. Validation failure returns structured errors and never invokes rendering. Existing structured `Plan` callers remain supported as a compatibility path.

## Compatibility Strategy

Changing `LLMPlanner.plan` from `Plan` to `SimpleExpressionPlan` would break existing callers and tests. Add a dedicated `SimpleExpressionPlanner` whose `plan` method returns `SimpleExpressionPlan`, and make it the default expression planner used by `ValueLogicGenerator`.

Injected legacy planners remain accepted. When an injected planner returns the existing `Plan`, the generator continues through the existing `build_ast`, AST validation, and `generate_expression` path. When it returns `SimpleExpressionPlan`, the generator uses the new validated path. This preserves old tests while moving the default runtime path to simple plans.

## Models and Result Contract

`ValueLogicRequest` gains `debug: bool = False`.

`ValueLogicResult` gains:

- `logic_type="validation_failed"` as an additional allowed result type;
- `validation_errors: list[dict[str, Any]]` with an empty default;
- `debug_info: dict[str, Any] | None`.

Successful non-debug responses retain their existing shape except for optional fields using defaults. On validation failure, `expression` is `None`, `source.source_type` remains `plan`, and `validation_errors` contains serialized `TypeValidationError` values. No exception is required for ordinary validation failure.

In debug mode, `debug_info` contains serialized `typed_context`, `simple_plan`, and `type_validation_result`. Non-debug responses set `debug_info=None` and do not expose internal typed context.

## Simple Planner

`SimpleExpressionPlanner` accepts node info, user query, filtered resources, and typed context. It calls a new prompt key and validates the response directly as `SimpleExpressionPlan`.

The prompt permits only:

- `definitions`: ordered `{name, expr}` objects;
- `return_expr`: one EDSL expression string;
- optional `target_return_type` matching the `TypeRef` JSON shape.

It instructs the model to use only roots, variables, fields, methods, and patterns present in Typed Expression Context; to preserve NamingSQL names and bindings; and to return strict JSON without markdown. Planner repair is outside this slice: malformed planner JSON remains an exception, while well-formed but semantically invalid expressions become structured validation failures.

## Validation Facade

`SimplePlanValidator.validate_simple_plan(simple_plan, typed_context, runtime)` is a narrow facade over `MethodChainValidator`. `runtime` contains `TypeRegistry` and `MethodRegistry`. The facade returns `ExpressionValidationResult` unchanged.

Definitions are validated and scoped in order, followed by `return_expr` and optional target type. The validator remains the single authority for reference, chain, lambda, conditional, binary, and return-type checks.

## Lightweight ASTBuilder

Add lightweight AST models:

- `SimpleDefinitionAst(name, expr)`;
- `SimpleExpressionProgramAst(definitions, return_expr)`.

`build_simple_ast(SimpleExpressionPlan)` copies validated strings into these models without reparsing or transforming them. It validates definition names as identifiers and rejects blank expression strings. This is an AST boundary for rendering, not a second expression parser.

The existing `build_ast(Plan)` behavior is unchanged.

## EDSL Renderer

`EDSLRenderer.render_simple_plan(SimpleExpressionProgramAst)` renders definitions in order as:

```text
def charge: fetch_one(E_QUERY_CHARGE, pair(it.ACCT_ID, $ctx$.acct.acctId));
```

The final line is `return_expr` verbatim. With no definitions, the output is only `return_expr`. It does not normalize whitespace inside expressions.

The generator calls `build_simple_ast` and the renderer only when `validation_result.is_valid` is true. A renderer spy test enforces this gate.

## Main Flow

The current repository flow becomes:

1. load resources;
2. filter to `FilteredEnvironment`;
3. build `TypedExpressionContext`;
4. call the configured planner with typed context;
5. if the result is legacy `Plan`, run the legacy path;
6. if the result is `SimpleExpressionPlan`, validate locally;
7. on failure, return `validation_failed` plus structured errors and optional debug data;
8. on success, build the lightweight AST and render final EDSL;
9. return the expression plus optional debug data.

NamingSQL selection still happens before typed-context construction. Existing authoritative selection checks remain in the legacy path; the simple path relies on the selected resources and local typed validation and does not broaden available resources.

## Tests

Tests follow red-green-refactor and include:

1. renderer unit tests for no definitions, one definition, and ordered multiple definitions;
2. ASTBuilder unit tests for copying valid plans and rejecting invalid definition names or blank expressions;
3. simple planner prompt/response contract tests;
4. end-to-end context method case producing the address `if` expression;
5. end-to-end query variable case producing a `charge` definition and `long2str` return;
6. end-to-end List `find` case producing a `charges` definition and lambda chain;
7. invalid String `addDays` case returning `METHOD_NOT_FOUND` and proving renderer was not called;
8. debug mode assertions for typed context, simple plan, and validation result;
9. legacy injected planner tests remaining green.

