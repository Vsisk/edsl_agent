# Expression Resource Model

Expression generation must work from selected resources rather than the full project state.

- Context resources describe already available values.
- BO resources describe structured domain objects and their fields.
- Naming SQL resources describe query-backed BO access.
- Function and method resources describe operations that can appear in an expression.
- Resource selection should keep enough metadata for generation and validation, but avoid unrelated project-wide data.
