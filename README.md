# ContextPack 与 NamingSQL 选择

统一上下文召回见 [ContextPackManager 指南](agent/context_pack/README.md)，基于召回结果的受约束决策见 [NamingSQL Selector 指南](agent/naming_sql_selector/README.md)。旧 Context Manager 仅保留底层与兼容组件。

ValueLogic 请求首先执行一次轻量布尔路由：开发 skill 与 OOTB 固定搜索，仅判断是否追加当前树；判断失败时使用全部上下文资源。构建出的单个 ContextPack 贯穿 spec、NamingSQL、typed-context 和 planner。

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
