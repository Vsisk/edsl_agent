# ContextPack 驱动的 NamingSQL Selector

`NamingSqlSelector` 是 ContextPack 召回之后的受约束决策层。请求必须携带已经构建好的 `ContextPack`；候选只能来自同一请求的权威 `LoadedResource`。

在 ValueLogic 调用链中，该 pack 已于 spec 生成前完成构建；Selector 必须消费 `GenerationContext` 中的同一对象，不得自行重新召回。

```python
selector = NamingSqlSelector(loaded_resource)
response = selector.select(NamingSqlSelectRequest(
    site_id=site_id,
    project_id=project_id,
    query=query,
    node=current_node,
    json_path=node_path,
    context_pack=context_pack,
    target_bo_name=target_bo_name,
    top_k=5,
))
```

选择过程依次执行：

1. `NamingSqlContextAdapter` 将 current-tree 事实、开发规范与 OOTB 参考压缩为有界信号；
2. `NamingSqlCandidateRetriever` 从 `LoadedResource.bo_registry` 构造 canonical 资产，先应用 BO 硬约束，再做确定性混合召回；
3. 可选 reranker 只能重新排序已召回的 opaque candidate IDs；
4. 所有返回项重新映射到 canonical 资产并生成连续 rank；
5. planner 与本地 validator 只能使用响应中的 Top-K。

成功响应的 `selection_mode` 为 `llm` 或 `deterministic_fallback`。已知 AI/输出错误会出现在 `warnings` 中且不会泄漏异常详情。`CONTEXT_PACK_FAILED` 和 `NO_NAMING_SQL_CANDIDATES` 是会终止选择的稳定失败码。

默认 Selector 不主动创建网络客户端，因此使用确定性模式。需要 LLM 精选时，通过 request-scoped factory 注入现有 `LLMReranker`；embedding 召回同样通过 `NamingSqlCandidateRetriever(hybrid_retriever=...)` 注入。

```powershell
.venv\Scripts\python.exe -m pytest tests/test_namingsql_selector_context_request.py tests/test_namingsql_context_adapter.py tests/test_namingsql_context_retrieval.py tests/test_namingsql_llm_selection.py -q
```
