# ContextPackManager（Phase 1）

`ContextPackManager` 是统一的本地上下文入口。调用方只提交当前操作节点、查询和显式资源白名单；管理器返回结构化 `ContextPack`，不直接生成 prompt。

`ValueLogicGenerator` 在每次请求开始时只构建一次 ContextPack。轻量 LLM 路由只判断是否需要 `current_tree`；`dev_skill` 与 `ootb_edsl` 固定召回。路由不可用或输出非法时启用全部三类资源，并记录 `CONTEXT_RESOURCE_ROUTE_FALLBACK`。

同一 pack 保存在 `GenerationContext` 中，显式传给 spec、NamingSQL Selector、typed-context builder 和 planner。Planner 使用 `ContextPackPromptRenderer` 的有界投影，不读取完整树或未召回资源。

## 公开调用

```python
from agent.context_pack import ContextPackRequest, ProjectContext, create_context_pack_manager

manager = create_context_pack_manager()
pack = manager.build(
    ContextPackRequest(
        node=current_node,
        query="生成客户完整姓名",
        resource_names=["dev_skill", "current_tree"],
    ),
    ProjectContext(
        current_tree=current_edsl_tree,
        ootb_tree=complete_ootb_edsl_tree,
        dev_skill_path=project_skill_path,
    ),
)
```

`resource_names` 是严格白名单。Phase 1 支持：

- `dev_skill`：从工程内自然语言 Markdown 召回领域取值配方；
- `current_tree`：搜索当前 EDSL 中实际存在的节点、字段和对当前节点可见的 local/iter；
- `ootb_edsl`：从另一棵更完整、覆盖取值逻辑的 OOTB 基线树召回有界范例。

默认 `agent/resource_manager/data/edsl_tree.json` 是当前树测试数据，不是 OOTB。生产调用必须通过 `ProjectContext.ootb_tree` 单独注入完整 OOTB 树。

NamingSQL 不属于 ContextPack 资源。它是 ContextPack 召回之后的受约束决策：`NamingSqlSelector` 综合 pack 中的当前树事实、开发规范和 OOTB 参考，并且只能从权威 `LoadedResource` 中选择 canonical NamingSQL。

## 输出与权威级别

`ContextPack.sections` 采用稳定顺序：`current_tree -> dev_skill -> ootb_edsl`。只输出本次实际申请且已注册的 sections。

- 当前树 item 是 `authoritative`；
- 开发 skill item 是 `normative`；
- OOTB item 是 `reference`。

Pack Builder 按 canonical locator/hash 校验结果，检测同 key 事实冲突，并按 exact 命中、authority 和 provider rank 执行预算裁剪。单个资源缺失时保留其他结果并返回 `partial`；所有资源均无可用 item 时返回 `failed`。

## 本地召回和降级

每个 Provider 先做硬过滤，再执行精确/词法召回、同源 rank fusion 和可选 embedding。Embedding 不可用时保留确定性结果并标记 `degraded`。不同资源的分数不会混成跨资源总分。

索引只帮助定位；Markdown 内容必须按受控 locator 回读并验证 SHA-256。文件检索不接受未注册根目录之外的路径。

## 验证

```powershell
python -m pytest tests/test_context_pack_models.py tests/test_context_pack_registry_manager.py tests/test_context_pack_search.py tests/test_context_pack_markdown_skill.py tests/test_context_pack_edsl_index.py tests/test_context_pack_current_tree.py tests/test_context_pack_ootb.py tests/test_context_pack_builder.py tests/test_context_pack_integration.py -q
```
