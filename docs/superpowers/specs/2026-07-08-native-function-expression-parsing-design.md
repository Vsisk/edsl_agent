# Native Function Expression Parsing Design

## Goal

Extend `EDSLExpressionParser` so a native function selected into the typed expression context can be parsed from its required qualified syntax:

```text
FunctionClass.functionName(arg1, arg2, ...)
```

The parsed expression must enter the existing Plan and AST pipeline as a generic `call` node. This change does not add a native-function-specific Plan or AST node.

## Source of Truth

`TypedExpressionContext.root_values` is authoritative for distinguishing native functions from member methods. A root is a native function only when:

- `source_type == "function"`; and
- its `expr` exactly provides the qualified name `FunctionClass.functionName`.

The parser must not infer a native function merely because an expression looks like `A.B(...)`. If the qualified name is absent from the typed context, existing variable, field, and member-method parsing remains in effect.

## Parsing

At parser initialization, collect function roots separately from context and local roots. During expression parsing, recognize a function root only when it starts the expression and is immediately followed by `(`.

The matching closing parenthesis must be found with delimiter- and string-aware scanning. Arguments are split with the existing top-level comma splitter and recursively parsed. The result is:

```text
CallExprPlanNode(type="call", name="FunctionClass.functionName", args=[...])
```

An optional suffix after the closing parenthesis is parsed as a member chain whose receiver is the function call. This supports expressions such as:

```text
FunctionClass.functionName(value).length()
```

Nested native calls are supported through recursive argument parsing.

## AST and Rendering

The existing `CallExprPlanNode -> CallNode` builder mapping is reused. The existing renderer already emits a `CallNode` as `name(arg1, arg2)`, preserving the qualified function name without special handling.

Member operations on a function result continue to use existing `field_access` and `method_call` nodes.

## Validation and Errors

The parser rejects malformed matched native calls, including unbalanced parentheses or unexpected text between the call and a member-chain suffix. Such failures use the existing `PARSE_FAILED` handling in `ValueLogicGenerator`.

Function availability is constrained by typed-context membership. Parameter signature/type validation is not added in this change; it can later be performed in the AST validation stage using the selected function resource metadata.

## Tests

Add coverage for:

- a typed function root parsed as a qualified generic call;
- recursively parsed context and literal arguments;
- nested native function calls;
- a member method chained from a native function result;
- an unregistered `A.B(...)` remaining a member-method expression;
- Plan-to-AST-to-render round trip preserving the native function syntax;
- malformed matched native calls producing structured `PARSE_FAILED` output.

