# ContextPackManager（Phase 1）

`ContextPackManager` 是统一的本地上下文入口。调用方只提交当前操作节点、查询和显式资源白名单；管理器返回结构化 `ContextPack`，不直接生成 prompt。

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

`namingsql` 已保留为资源名，但 Phase 1 尚未注册对应 Provider；请求它会返回 `RESOURCE_NOT_REGISTERED`，直到后续迁移完成。

## 输出与权威级别

`ContextPack.sections` 采用稳定顺序：`current_tree -> namingsql -> dev_skill -> ootb_edsl`。只输出本次实际申请且已注册的 sections。

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
