# AST Validation Gate Design

Remove pre-parse SimplePlan type validation from value generation. The SimplePlan path becomes `parse_plan → build_ast → validate_ast → generate_expression`.

Parser, AST build, and AST validation exceptions are converted to `validation_failed` results with `PARSE_FAILED`, `AST_BUILD_FAILED`, or `AST_VALIDATION_FAILED`. Rendering is never called after a failure. Debug output contains typed context, SimplePlan, optional parsed Plan, and `ast_validation_result`; it no longer contains `type_validation_result`.

The standalone type-validation modules remain available but are not called by ValueLogicGenerator.
