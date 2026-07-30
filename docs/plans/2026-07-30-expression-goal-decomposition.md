# 表达式 Goal 分解与并行求解实现计划

> **给 Codex：** 按本计划使用测试驱动开发完成实现。

**目标：** 在资源搜索前把 query 分解为受约束的逻辑骨架，使 Literal 直接提交、多个独立资源 Goal 并行求解并按原顺序合并。

**相关设计文档：** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** 语义网关输出 single、literal 或 concat 三类有界骨架。single 延续单 Goal 路线；literal 不触发关键词和资源搜索；concat 将资源操作数转换为独立 Value Goal，以隔离状态并行求解，最后按操作数位置合并为一个 composition resolution。

**技术栈：** Python、Pydantic、线程池、pytest

**范围 / 非范围：** 本轮支持固定字符串和字符串 concat；不开放任意函数名或任意表达式 AST，不修改公开 ValueLogicResult，不触碰工作区已有 TypedContext/Planner 未提交改动。

---

## Phase #1: 受约束逻辑骨架

### Task #1: Query 分解模型与语义网关

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/models.py`
- 修改：`agent/spec_orchestration/semantic.py`
- 修改：`prompt.json`
- 验证：`tests/test_spec_orchestrator_semantic.py`
- 功能：输出 single、literal、concat 及有序操作数。
- 实现说明：操作数只允许 resource 或 literal；非法响应降级为 single。
- 预期验证结果：Literal 不会被误建为资源 Goal，未知操作符和空组合被拒绝。

## Phase #2: Literal 快速路径与并行 Goal

### Task #2: Orchestrator 分支求解

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/orchestrator.py`
- 验证：`tests/test_spec_orchestrator.py`
- 功能：固定字符串直接形成 committed resolution；concat 的资源操作数独立并行求解。
- 实现说明：每个并行分支拥有独立预算、trace 和回滚状态；按操作数位置确定性合并；必要分支任一失败则组合失败。
- 预期验证结果：固定字符串零搜索；first name 和 last name 两个 Goal 均求解且组合顺序稳定。

## Phase #3: 组合结果编译

### Task #3: 自然语言逻辑与资源并集

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/compiler.py`
- 修改：`docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`
- 验证：`tests/test_spec_orchestrator_compiler.py`
- 功能：编译 concat 骨架、Literal 和各分支 committed resources。
- 实现说明：Literal 不进入 FilteredEnvironment；资源列表取成功分支并集。
- 预期验证结果：最终 Spec 明确 `first_name + "_" + last_name` 的有序拼接，完整回归通过。
