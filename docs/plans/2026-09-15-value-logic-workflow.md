# Value Logic Workflow 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将 ValueLogicGenerator 顶层流程改造为 `value_logic_generation` workflow，内部管理 SQL / BO field / summary / expression 分支，并把入口构建的资源、business scope、context pack 转为 workflow context/artifacts。

**相关设计文档：** 当前用户需求，无独立批准设计文档。

**架构：** `agent/workflows/value_logic` 承载 ValueLogic 具体 workflow。Harness 只路由到 `value_logic_generation`，ValueLogic WorkflowRuntime 内部通过 deterministic branch transition 选择 sql/bo/summary/expression 分支；Expression 子 workflow 仍作为 ExpressionBranchStage 内部能力被调用。

**技术栈：** Python dataclass、agent.workflow Runtime/Context/Transition、pytest。

**范围 / 非范围：** 本轮保留现有业务函数实现，通过 stage 包装调用；不重写 SQL/BO/expression 业务算法，不修复当前缺失的外部业务模块。

---

## Phase #1: ValueLogic Workflow 定义

### Task #1: ValueLogic stage 与 definition

**状态：** Finished

**文件：**
- 创建：`agent/workflows/value_logic/*`
- 修改：`agent/workflow/transition.py`
- 验证：`tests/test_value_logic_workflow.py`

- 功能：定义 build_context、route_target、sql_branch、bo_field_branch、summary_branch、expression_branch、finalize stages。
- 实现说明：build_context 输出 `generation_context` 和 `target`；route_target 输出 `branch`；branch stage 输出 `value_logic_result` 或回落到 expression branch。
- 预期验证结果：SQL/BO/expression 分支可由 workflow transition 驱动。
- 完成时间：2026-09-15

## Phase #2: ValueLogicGenerator 接入

### Task #2: generate() 入口委托 workflow

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`
- 验证：`python -m py_compile agent/value_logic_generator.py`

- 功能：`generate()` 不再直接选择 SQL/BO/expression 分支，而是调用 `ValueLogicWorkflowHandler`。
- 实现说明：抽出 `_prepare_generation_context()`、`_resolve_sql_branch()`、`_resolve_normal_field_logic()`，让 stage 可调用且保留旧 fallback 方法兼容。
- 预期验证结果：现有入口上下文作为 workflow artifact 而不是 generator 局部状态。
- 完成时间：2026-09-15

## Phase #3: Harness 路由升级

### Task #3: Harness 默认能力改为 value_logic_generation

**状态：** Finished

**文件：**
- 修改：`agent/harness/defaults.py`
- 修改：`agent/harness/analyzer.py`
- 修改：`tests/test_harness_runtime.py`

- 功能：用户表达式/取值逻辑请求路由到 `value_logic_generation`，`expression_generation` 作为内部可复用 workflow metadata 保留。
- 预期验证结果：Harness 不理解 ValueLogic 内部 SQL/BO/expression 分支。
- 完成时间：2026-09-15
