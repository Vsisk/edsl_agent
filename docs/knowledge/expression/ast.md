# Expression AST Rules

Expression AST validation is the boundary between planning and final output.

- Validate resource references against the selected resource metadata.
- Validate method calls against available type and method information.
- Use validation errors as repair observations for the next generation attempt.
- Final output should be produced only after AST validation succeeds.
