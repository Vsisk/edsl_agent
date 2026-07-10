# NamingSQL Context Manager

统一的本地上下文入口及 Phase 1 资源说明见 [ContextPackManager 指南](agent/context_pack/README.md)。

Configure the OpenAI-compatible embedding and language-model clients with
`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_BASE_MODEL`, and
`OPENAI_EMBEDDING_MODEL` (default: `bge-m3`). Set the
embedding model explicitly; no provider default is assumed. Both clients are
mandatory: missing configuration or
an embedding, reranking, or organizer failure stops context construction with a
diagnostic error instead of silently falling back to deterministic ranking.

NamingSQL selection routes the request's `top_k` candidates through semantic
recall, LLM reranking, and LLM organization. Global rules are loaded from
`agent_rules/`; reference fixtures are loaded from
`agent/context_manager/mock_data/`. Tests use injected fake embedding and LLM
clients and do not require network access.

Local embeddings default to `EMBEDDING_PROVIDER=local_bge_m3` and
`LOCAL_EMBEDDING_MODEL_PATH=D:\models\bge-m3`. The LLM continues using the
existing OpenAI-compatible endpoint; local embedding does not use that base URL.

完整的架构、扩展与排错说明见 [Context Manager 维护指南](agent/context_manager/README.md)。
