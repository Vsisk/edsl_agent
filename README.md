# NamingSQL Context Manager

Configure the OpenAI-compatible embedding and language-model clients with
`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_BASE_MODEL`, and
`OPENAI_EMBEDDING_MODEL` (for example, `text-embedding-3-small`). Set the
embedding model explicitly; no provider default is assumed. Both clients are
mandatory: missing configuration or
an embedding, reranking, or organizer failure stops context construction with a
diagnostic error instead of silently falling back to deterministic ranking.

NamingSQL selection routes the request's `top_k` candidates through semantic
recall, LLM reranking, and LLM organization. Global rules are loaded from
`agent_rules/`; reference fixtures are loaded from
`agent/context_manager/mock_data/`. Tests use injected fake embedding and LLM
clients and do not require network access.

完整的架构、扩展与排错说明见 [Context Manager 维护指南](agent/context_manager/README.md)。
