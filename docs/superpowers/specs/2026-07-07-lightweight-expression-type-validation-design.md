# Lightweight Expression Type Validation Design

## Scope

Add a local lightweight parser and static type validator for string expressions stored in a new `SimpleExpressionPlan`. The validator processes definitions in order, records each inferred definition type in a scope, then validates the return expression and optional target return type.

This change does not modify planner output models, parse planner AST nodes, or change ASTBuilder, AST validation, or rendering.

## Plan and Result Models

`SimpleDefinition` contains `name: str` and `expr: str`.

`SimpleExpressionPlan` contains:

- `definitions: list[SimpleDefinition]`
- `return_expr: str`
- `target_return_type: TypeRef | None`

`TypeScope` is a nested variable environment. A child scope inherits parent variables and may override `it` for a lambda. Definitions are added only after their expressions resolve successfully.

`ExpressionValidationResult` contains:

- `return_type: TypeRef | None`
- `errors: list[TypeValidationError]`
- `definition_types: dict[str, TypeRef]`
- `is_valid: bool`

`TypeValidationError` contains exactly the requested error context: error type, full expression, optional token, owner, expected and actual types, and a stable human-readable message.

## Components

`ExpressionTokenizer` performs character-level scans shared by the parser. It tracks quoted strings with escapes, parenthesis depth, brace depth, and numeric decimal points. It exposes bounded helpers for splitting top-level commas and locating top-level binary operators.

`TopLevelDotSplitter` implements `split_top_level_dot_chain(expr)`. It never calls `str.split(".")`. A dot is a separator only when it is outside strings, parentheses, and braces and is not the decimal point between digits. The resulting pieces preserve their original text. For `$ctx$` and `$local$`, `MethodChainParser` rejoins the leading pieces using longest-prefix lookup against typed roots, thereby separating the authoritative context path from its remaining field chain.

`MethodChainParser` converts split pieces to `ChainToken` values:

- first item: `root`;
- identifier: `field`;
- `name(...)`: `method_call`, with arguments split only at top-level commas;
- `name{...}`: `lambda_method_call`, with the brace body stored as `lambda_expr`.

Context paths are resolved before ordinary chain parsing by longest-prefix matching against typed roots. For `$ctx$.address.addr1.length()`, `$ctx$.address` becomes the root and `addr1`, `length()` remain chain tokens.

`ExpressionTypeResolver` recursively resolves literals, `if`, binary expressions, special fetch calls, and method chains. `MethodChainValidator` performs field and method transitions and produces structured errors.

## Root and Fetch Resolution

The resolver consumes `TypedExpressionContext`, `TypeRegistry`, and `MethodRegistry`.

It builds a root table from typed context root values and their expanded access views. Rendered type strings such as `logic.Address`, `List<bo.BB_BILL_CHARGE>`, and `Map<basic.String,bo.BB_BILL_CHARGE>` are parsed back into `TypeRef` by a strict local type-text parser.

For a context or local expression, the longest typed root expression that is an exact prefix is selected. A `$ctx$` or `$local$` expression with no matching root reports `UNKNOWN_CONTEXT_PATH`.

Ordinary identifiers resolve through `TypeScope`. A missing identifier reports `UNKNOWN_VARIABLE`; an unsupported root form reports `UNKNOWN_ROOT`.

`fetch(...)` and `fetch_one(...)` are special roots. Their return types are taken only from concrete `TypedVarTemplate.definition_expr` or `TypedExpressionPattern.expression` entries whose fetch name matches. `fetch` must resolve to a list type and `fetch_one` to its element/object type. The validator does not infer a BO from an arbitrary function name.

## Chain Type Transitions

For a field token:

- object owners use `TypeRegistry.resolve_field`;
- a basic owner reports `FIELD_ACCESS_ON_BASIC_TYPE`;
- a list owner reports `LIST_FIELD_ACCESS_WITHOUT_ELEMENT_METHOD`;
- an object with no matching field reports `FIELD_NOT_FOUND`.

For a method token, each argument expression is recursively resolved. `MethodRegistry.methods_for(owner)` determines whether the method name exists and whether any overload has the supplied arity. `MethodRegistry.match` performs the final type match. Errors are classified in this order: `METHOD_NOT_FOUND`, `METHOD_ARG_COUNT_MISMATCH`, then `METHOD_ARG_TYPE_MISMATCH`.

For a lambda method, the owner must be `List<T>`. Failure to obtain `T` reports `LAMBDA_IT_TYPE_NOT_FOUND`. A child scope binds `it=T`, resolves the lambda body, and requires `basic.boolean`; otherwise it reports `LAMBDA_EXPR_NOT_BOOLEAN`. The list method's resulting type then becomes the current chain type.

## Conditional and Binary Expressions

`if(condition, then_expr, else_expr)` is recognized only as a complete top-level call. Its three arguments are split with the tokenizer. The condition must resolve to `basic.boolean`, otherwise `IF_CONDITION_NOT_BOOLEAN`. Both branches must resolve to identical `TypeRef` values, otherwise `IF_BRANCH_TYPE_MISMATCH`. A valid `if` returns the branch type.

Binary operators are found only at top level and use precedence groups:

1. boolean OR;
2. boolean AND;
3. equality and ordering comparisons;
4. addition and subtraction;
5. multiplication and division.

Ordering and arithmetic accept numeric basic types (`int`, `long`, `decimal`, and their existing resource spellings). Ordering and equality return `basic.boolean`. Boolean operators require `basic.boolean` operands and return `basic.boolean`. Arithmetic requires compatible numeric operands and returns the wider operand type. Unary operators and implicit conversions are outside this phase.

String, boolean, integer, long, and decimal literals receive basic types. Empty string is `basic.String`. Method arguments and binary operands reuse the same resolver.

## Error Handling

Parsing and validation failures are returned, not raised as business exceptions. The resolver stops the current expression branch after an error that prevents determining its type, while continuing with later definitions or return validation when possible.

Supported error types are:

- `UNKNOWN_ROOT`
- `UNKNOWN_CONTEXT_PATH`
- `UNKNOWN_VARIABLE`
- `FIELD_NOT_FOUND`
- `FIELD_ACCESS_ON_BASIC_TYPE`
- `METHOD_NOT_FOUND`
- `METHOD_ARG_COUNT_MISMATCH`
- `METHOD_ARG_TYPE_MISMATCH`
- `LIST_FIELD_ACCESS_WITHOUT_ELEMENT_METHOD`
- `LAMBDA_IT_TYPE_NOT_FOUND`
- `LAMBDA_EXPR_NOT_BOOLEAN`
- `IF_CONDITION_NOT_BOOLEAN`
- `IF_BRANCH_TYPE_MISMATCH`
- `TARGET_RETURN_TYPE_MISMATCH`

If the return expression resolves and `target_return_type` differs, the validator appends `TARGET_RETURN_TYPE_MISMATCH` with expected and actual types.

## Testing

Tests follow red-green-refactor and cover:

1. top-level dot splitting across context paths, ordinary chains, quoted date formats, decimals, nested arguments, and lambda braces;
2. `$ctx$.address.addr1.length()` resolving to `basic.int`;
3. a valid String-returning `if` expression;
4. the dateValue/addDays/toString chain without splitting `yyyy.MM.dd`;
5. ordered definition scope for `charge` from `fetch_one`;
6. list lambda binding for `charges.find{it.CHARGE_AMT > 0}.CHARGE_AMT`;
7. structured method-not-found, field-on-basic, list-field-access, and if-branch-mismatch errors;
8. representative argument count/type errors, non-boolean lambdas, unknown roots/variables/contexts, and target mismatch.
