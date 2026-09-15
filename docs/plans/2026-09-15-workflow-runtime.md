# WorkflowRuntime 通用化实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将 Expression Workflow 的执行控制权迁移到通用 `WorkflowRuntime`，让具体业务 workflow 只提供 Definition 和 Stage。

**相关设计文档：** 用户本轮请求（WorkflowDefinition + WorkflowRuntime 边界要求）

**架构：** 在 `agent/expression_workflow/core.py` 中定义领域无关 `WorkflowDefinition`，新增/改造 `agent/expression_workflow/executor.py` 为通用 `WorkflowRuntime`。Expression 侧的 `ExpressionWorkflowFactory` 只负责构造 stages、`default_transitions` 和 `terminal_stages`，`ExpressionWorkflowHandler` 只初始化 `WorkflowRunState` 并委托 Runtime。

**技术栈：** Python dataclasses、pytest。

**范围 / 非范围：** 本轮只支持固定 default transition，禁止 loop，不实现动态 retry、TransitionPolicy、FailureDiagnoser 或回边。

---

## Phase #1: Runtime 抽象

### Task #1: 定义通用 WorkflowDefinition

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/core.py`
- 修改：`agent/expression_workflow/definition.py`

- 功能：`WorkflowDefinition` 包含 `name`、`entry_stage`、`stages`、`default_transitions`、`terminal_stages`。
- 实现说明：Definition 只提供结构查询，不执行 stage。
- 预期验证结果：Expression factory 返回通用 Definition。

### Task #2: 实现 WorkflowRuntime

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/executor.py`

- 功能：Runtime 提供 `run()`、`run_stage()`、`apply_stage_result()`、`resolve_next_stage()`。
- 实现说明：Runtime 不依赖 Expression 领域；当前 `resolve_next_stage()` 只读 `default_transitions` 并禁止 loop。
- 预期验证结果：Expression Workflow 仍按原顺序执行。

## Phase #2: Expression 接入

### Task #3: Handler 改用 Runtime

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/handler.py`
- 修改：`agent/expression_workflow/__init__.py`
- 修改：`agent/value_logic_generator.py`

- 功能：删除/弱化 `LinearWorkflowExecutor` 概念，Expression 通过 `WorkflowRuntime` 执行 Definition。
- 实现说明：保留 alias 兼容但主路径使用 Runtime。
- 预期验证结果：`ValueLogicGenerator` 行为不变，不出现 stage 调用链。

## Phase #3: 回归验证

### Task #4: baseline 回归

**状态：** Finished

**文件：**
- 验证：全量 `pytest`

- 功能：确认最终表达式行为保持 baseline。
- 实现说明：运行 `.venv` 内 pytest。
- 预期验证结果：baseline 全通过。
