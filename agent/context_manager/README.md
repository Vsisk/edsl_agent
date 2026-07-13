# Context Manager 底层组件

`agent.context_manager` 现在是兼容与底层能力包，不再是 NamingSQL 选择的生产编排入口。

仍被复用的组件包括：

- `ContextAsset`、`NamingSqlCandidate` 和 evidence 等领域模型；
- `ResourceAssetBuilder` 对权威 `LoadedResource` 的 canonical 转换；
- lexical、embedding、hybrid retrieval 与 `LLMReranker`；
- 稳定错误码以及旧链路的回归测试。

旧的 `ContextManager.build_context(BuildContextRequest)`、resolver 固定序列和 organizer/assembler 暂时保留，供兼容测试与后续删除审计使用。新生产调用不得通过它召回 NamingSQL 上下文。

## 当前生产数据流

```text
ContextPackManager(current_tree, dev_skill, ootb_edsl)
  -> ContextPack
  -> NamingSqlSelector(ContextPack + LoadedResource)
  -> deterministic canonical Top-K
  -> optional LLM rerank
  -> NamingSqlSelectResponse
  -> typed context / planner / validator
```

LLM 或 embedding 配置、传输、解析或输出校验失败时，Selector 返回确定性 Top-K，并将 `selection_mode` 标记为 `deterministic_fallback`。未知 ID、重复 ID 和越界结果不会进入响应。只有 ContextPack 不可用、权威注册表无合法候选或未识别的程序错误才终止选择。

新增功能应放在 `agent/context_pack` 或 `agent/naming_sql_selector` 的对应边界内；不要向旧 `ContextManager` 增加新的跨资源编排职责。

## 验证

```powershell
.venv\Scripts\python.exe -m pytest tests/test_context_retrieval.py tests/test_llm_reranker_contract.py -q
.venv\Scripts\python.exe -m pytest tests/test_namingsql_context_adapter.py tests/test_namingsql_context_retrieval.py tests/test_namingsql_llm_selection.py -q
```
