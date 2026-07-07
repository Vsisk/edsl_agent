# Simple Expression Plan End-to-End Design

## Scope

Connect typed context, `SimpleExpressionPlan`, local type validation, EDSL string parsing, the existing `Plan`/AST pipeline, and expression generation. Validation failure returns structured errors and never invokes parsing or rendering. Existing structured `Plan` callers remain supported.

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

## EDSL Expression Parser

After static type validation succeeds, `EDSLExpressionParser` converts every definition expression and the return expression into existing planner nodes. It returns a normal `Plan` containing ordered top-level `DefExprPlanNode` items followed by one `ReturnExprPlanNode`.

The parser reuses the stateful tokenizer and top-level expression logic from the static validator. It parses literals, context roots, definition variables, fields, ordinary calls, `if`, binary comparisons/logical expressions, `fetch`/`fetch_one` with `pair` parameters, member methods, and lambda methods.

Two node families are added to both planner and AST unions:

- `FieldAccessExprPlanNode` / `FieldAccessNode` with `receiver` and `field`;
- `MethodCallExprPlanNode` / `MethodCallNode` with `receiver`, `name`, ordinary `args`, and optional parsed `lambda_expr`.

Context roots become `ContextPathExprPlanNode`; definition variables become `VariableRefExprPlanNode`. Each field segment wraps the current receiver in a field-access node. Each method segment wraps it in a method-call node. Lambda bodies are recursively parsed into existing comparison/logical/call/path nodes and stored as `lambda_expr`, not raw text.

NamingSQL expressions such as `fetch_one(E_QUERY_CHARGE, pair(it.ACCT_ID, $ctx$.acct.acctId))` become `FetchOneExprPlanNode` with `FetchParam(name="it.ACCT_ID", value=<parsed context expression>)`.

## Existing AST and Rendering Pipeline

`build_ast` is extended to convert field-access and method-call planner nodes into their AST equivalents. `validate_ast` recursively validates receivers, arguments, lambda bodies, and nonblank names/fields. `generate_expression` renders:

- field access as `<receiver>.<field>`;
- ordinary member methods as `<receiver>.<name>(<args>)`;
- lambda methods as `<receiver>.<name>{<lambda_expr>}`.

Definitions continue through the existing `DefNode` and return through `ReturnNode`. The generator's existing definition rendering is adjusted to the required colon/semicolon form:

```text
def charge: fetch_one(E_QUERY_CHARGE, pair(it.ACCT_ID, $ctx$.acct.acctId));
```

The final return node renders as its contained expression. There is no separate lightweight renderer in the main flow.

## Main Flow

The current repository flow becomes:

1. load resources;
2. filter to `FilteredEnvironment`;
3. build `TypedExpressionContext`;
4. call the configured planner with typed context;
5. if the result is legacy `Plan`, run the legacy path;
6. if the result is `SimpleExpressionPlan`, validate locally;
7. on failure, return `validation_failed` plus structured errors and optional debug data;
8. on success, parse the SimplePlan strings into a normal `Plan`, call `build_ast`, `validate_ast`, and `generate_expression`;
9. return the expression plus optional debug data.

NamingSQL selection still happens before typed-context construction. Existing authoritative selection checks remain in the legacy path; the simple path relies on the selected resources and local typed validation and does not broaden available resources.

## Tests

Tests follow red-green-refactor and include:

1. parser unit tests for context/variable method chains, field access, lambda methods, `if`, comparisons, fetch, and pair bindings;
2. ASTBuilder, AST validator, and generator tests for the new field-access and method-call nodes;
3. simple planner prompt/response contract tests;
4. end-to-end context method case producing the address `if` expression;
5. end-to-end query variable case producing a `charge` definition and `long2str` return;
6. end-to-end List `find` case producing a `charges` definition and lambda chain;
7. invalid String `addDays` case returning `METHOD_NOT_FOUND` and proving parsing/AST generation was not called;
8. debug mode assertions for typed context, simple plan, and validation result;
9. legacy injected planner tests remaining green.

