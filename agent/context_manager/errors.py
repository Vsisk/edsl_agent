class ContextBuildError(RuntimeError):
    """A context-building failure with a stable machine-readable code."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


AI_CONFIGURATION_REQUIRED = "AI_CONFIGURATION_REQUIRED"
EMBEDDING_FAILED = "EMBEDDING_FAILED"
LLM_RERANK_FAILED = "LLM_RERANK_FAILED"
LLM_ORGANIZER_FAILED = "LLM_ORGANIZER_FAILED"
INVALID_LLM_OUTPUT = "INVALID_LLM_OUTPUT"
RULE_FILE_MISSING = "RULE_FILE_MISSING"
EDSL_NODE_NOT_FOUND = "EDSL_NODE_NOT_FOUND"
UNSUPPORTED_CONTEXT_CHAIN = "UNSUPPORTED_CONTEXT_CHAIN"
NO_NAMING_SQL_CANDIDATES = "NO_NAMING_SQL_CANDIDATES"
