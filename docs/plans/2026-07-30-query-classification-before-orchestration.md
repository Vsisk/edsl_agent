# 编排前 Query 分类实现计划

> **给 Codex：** 按本计划使用测试驱动开发完成实现。

**目标：** 在 SpecOrchestrator 进入求解前，先由 LLM 将 query 分类为固定字符串、单目标或多目标，并仅对多目标执行第二阶段拆解。

**相关设计文档：** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** 第一阶段只输出 `fixed_string / single_goal / multi_goal` 及固定字符串内容，不生成目标骨架。固定字符串直接返回；单目标复用现有根 Goal 递归求解；多目标才调用受约束拆解器生成 concat/if 骨架，各资源操作数并行复用单目标求解逻辑。

**技术栈：** Python、Pydantic、pytest

**范围 / 非范围：** 调整入口职责和 Prompt；保留现有 ValueGoal、ResolvedGoal 与资源搜索数据结构，不修改公开 ValueLogicResult。

---

## Phase #1: 分类契约

### Task #1: 分类模型与语义网关

**状态：** Finished

**文件：**

- 修改：`agent/spec_orchestration/models.py`
- 修改：`agent/spec_orchestration/semantic.py`
- 修改：`prompt.json`
- 验证：`tests/test_spec_orchestrator_semantic.py`
- 功能：第一阶段严格分类；第二阶段仅拆解多目标。
- 实现说明：非法分类降级到 single_goal；非法多目标拆解降级到 single 骨架并由编排器走单目标逻辑。
- 预期验证结果：分类与拆解分别使用不同 Prompt，固定/单目标不会调用拆解 Prompt。

## Phase #2: 编排入口

### Task #2: 三分支路由与并行复用

**状态：** Finished

**文件：**

- 修改：`agent/spec_orchestration/orchestrator.py`
- 修改：`agent/spec_orchestration/__init__.py`
- 修改：`docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`
- 验证：`tests/test_spec_orchestrator.py`
- 功能：固定字符串直接提交；单目标走原逻辑；多目标拆解并并行调用 `_resolve_goal`。
- 实现说明：分类由 LLM 决定，路由和“是否触发拆解”由代码决定。
- 预期验证结果：三类入口的 LLM 调用顺序与资源搜索次数被测试锁定。
