# ContextPack 与 NamingSQL 选择

统一上下文召回见 [ContextPackManager 指南](agent/context_pack/README.md)，基于召回结果的受约束决策见 [NamingSQL Selector 指南](agent/naming_sql_selector/README.md)。旧 Context Manager 仅保留底层与兼容组件。

Configure the OpenAI-compatible embedding and language-model clients with
`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_BASE_MODEL`, and
`OPENAI_EMBEDDING_MODEL` (default: `bge-m3`). Set the
embedding model explicitly; no provider default is assumed. AI clients are
optional: missing configuration or invalid AI output falls back to deterministic
canonical ranking and is reported through `selection_mode` and `warnings`.

NamingSQL selection consumes a previously built ContextPack, constructs candidates
only from the current `LoadedResource`, and optionally routes the bounded Top-K
through LLM reranking. Tests use injected fake embedding and LLM clients and do
not require network access.

Local embeddings default to `EMBEDDING_PROVIDER=local_bge_m3` and
`LOCAL_EMBEDDING_MODEL_PATH=D:\models\bge-m3`. The LLM continues using the
existing OpenAI-compatible endpoint; local embedding does not use that base URL.

完整的架构、扩展与排错说明见 [Context Manager 维护指南](agent/context_manager/README.md)。
