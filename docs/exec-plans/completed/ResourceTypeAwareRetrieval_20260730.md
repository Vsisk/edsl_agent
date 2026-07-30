# ResourceTypeAwareRetrieval_20260730

## 关联设计文档

- [ResourceTypeAwareRetrieval_20260730](../../design-docs/ResourceTypeAwareRetrieval_20260730.md)

## Stage #1: 搜索契约与确定性 Context

### 任务 #1: 建立失败测试和 Context 匹配策略

**Status:** Finished

**Files:**

- Modify: `tests/test_spec_orchestrator_search.py`
- Modify: `agent/spec_orchestration/search.py`

功能：验证 Context 仅根据名称/path 和低优先级 annotation/tag 匹配，并且不调用 embedding。

实现说明：增加稳定匹配等级，保留 canonical Registry 引用和现有 limit 契约。

预期验证结果：新增测试经历 RED 后转为 GREEN，现有 Context 搜索测试通过。

## Stage #2: BO Field 向量召回

### 任务 #2: 实现 Property 粒度独立关键词评分

**Status:** Finished

**Files:**

- Modify: `tests/test_spec_orchestrator_search.py`
- Modify: `agent/spec_orchestration/search.py`

功能：对 `keywords + aliases` 分别计算字段余弦分数并取最大值，返回 canonical BO 和 Property。

实现说明：加入 exact 优先、negative 排除、Top 30 粗召回、稳定排序、向量校验和词法降级。

预期验证结果：多关键词、alias、负向词、exact 优先和 embedding 失败测试通过。

## Stage #3: Function 混合召回

### 任务 #3: 增加结构过滤与有界向量候选

**Status:** Finished

**Files:**

- Modify: `tests/test_spec_orchestrator_search.py`
- Modify: `agent/spec_orchestration/search.py`

功能：Function 在返回类型/基数过滤后进行 Top 20 向量粗召回，仍由 Coverage LLM 最终选择。

实现说明：函数搜索文本包含功能、类别、tag、参数和输出；候选保留真实 required inputs 与向量证据。

预期验证结果：不兼容函数不会进入 embedding，兼容函数按最大余弦分数排序，失败时有界降级。

## Stage #4: 集成与完成验证

### 任务 #4: 回归验证并回写计划

**Status:** Finished

**Files:**

- Verify: `tests/test_spec_orchestrator_search.py`
- Verify: `tests/test_spec_orchestrator.py`
- Verify: Spec Orchestration 相关测试集
- Modify: `docs/exec-plans/active/ResourceTypeAwareRetrieval_20260730.md`

功能：确认公开契约、递归搜索和 Coverage 选择流程保持兼容。

实现说明：运行专项测试和完整回归；仅在新鲜验证证据支持时将所有任务状态更新为 `Finished`。

预期验证结果：专项测试零失败；完整回归结果与工作区已有改动影响被明确记录。

验证记录：

- `python -m compileall -q agent/spec_orchestration/search.py agent/value_logic_generator.py`
- Spec Orchestrator 专项：30 passed
- `tests/test_value_logic_generator.py`：34 passed, 2 skipped
- 完整 pytest：856 passed, 6 skipped, 4 subtests passed
