# Expression Return Type Rules

Return type metadata constrains expression planning and validation.

- Normalize return types before comparing them.
- Preserve list element type when the expression returns a collection.
- Treat missing or unknown return type as a validation risk.
- Inspect target and source return types before finalizing an expression.
