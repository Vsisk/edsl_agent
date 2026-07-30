# Resource Embedding 分批计算实现计划

> **给 Claude：** 必需工作流：使用 test-driven-development 逐任务实现此计划。

**目标：** 对仍使用 embedding 的 Function 资源执行有界批次计算并保持现有排序与缓存语义；BO Property 后续改为确定性名称匹配，不再使用 embedding。

**相关设计文档：** `docs/design-docs/ResourceTypeAwareRetrieval_20260730.md`

**架构：** `OrchestratorResourceSearch` 仍一次计算当前 Goal 的关键词向量，但将尚未缓存的资源文档按 `embedding_batch_size` 切片调用 embedding client。批次结果按输入顺序合并、统一校验并写入现有实例缓存；任一批失败时沿用有界词法降级。

**技术栈：** Python、Pydantic、pytest、现有 `EmbeddingClient`

**范围 / 非范围：** 分批能力保留给 Function 资源向量计算路径；BO Field 最终不使用该路径；不改变 Context、LLM Coverage、相似度公式和持久化策略。

---

## Stage #1: 分批契约

### Task #1: 添加资源 embedding 最大批次测试

**状态：** Finished

**文件：**

- 修改：`tests/test_spec_orchestrator_search.py`
- 验证：`tests/test_spec_orchestrator_search.py`

- 功能：证明 Function 关键词只计算一次，任一 Function 资源 embedding 调用不超过配置的 batch size。
- 实现说明：通过 fake embedding client 记录每次输入；显式传入小批次以覆盖多批行为。
- 预期验证结果：现有一次性 embedding 实现产生 RED。

## Stage #2: 搜索实现

### Task #2: 分离查询向量与资源向量批次

**状态：** Finished

**文件：**

- 修改：`agent/spec_orchestration/search.py`
- 修改：`docs/design-docs/ResourceTypeAwareRetrieval_20260730.md`
- 验证：`tests/test_spec_orchestrator_search.py`

- 功能：查询关键词单独 embedding，未缓存资源按固定大小分批 embedding。
- 实现说明：构造函数支持显式 batch size；未显式配置时优先读取 embedding client settings 的 `local_embedding_batch_size`，否则使用安全默认值。
- 预期验证结果：多批输入顺序、最大批次、缓存复用和失败降级测试均通过。

## Stage #3: 回归验证

### Task #3: 完整验证并回写状态

**状态：** Finished

**文件：**

- 验证：`tests/test_spec_orchestrator_search.py`
- 验证：Spec Orchestrator 测试集
- 验证：完整 pytest
- 修改：`docs/exec-plans/active/ResourceEmbeddingBatching_20260730.md`

- 功能：确认分批不改变候选排序、Function 过滤和完整生成链路。
- 实现说明：执行专项、模块级和完整测试，记录新鲜验证结果。
- 预期验证结果：所有相关测试通过且无新增回归。

验证记录：

- 最终实现中 BO Field 已退出 embedding 路径，batch 行为由 Function 搜索测试继续覆盖。
- `tests/test_spec_orchestrator_search.py`：11 passed
- 其余 Spec Orchestrator 测试：18 passed
- 完整 pytest：855 passed, 6 skipped, 4 subtests passed
