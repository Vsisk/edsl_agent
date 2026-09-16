# Workflow Package Split 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 删除兼容用 `StageInputBinder`，并将当前 `expression_workflow` 拆分为通用 workflow 层与 Expression 具体 workflow 层。

**相关设计文档：** 当前用户需求，无独立批准设计文档。

**架构：** `agent/workflow` 承载通用 Stage/Runtime/Context/Transition/Capability 基础设施；`agent/workflows/expression` 承载 ExpressionWorkflowDefinition、handler、environment、result adapter、capability defaults 和 failure taxonomy。

**技术栈：** Python dataclass、现有 WorkflowRuntime / ContextAssembler、pytest。

**范围 / 非范围：** 本轮移动包结构、更新 imports、删除 binder；不迁移当前缺失的 `agent.expression_generate_op.stages` 业务 Stage 实现。

---

## Phase #1: 通用 workflow 包

### Task #1: 移动通用模块并删除 binder

**状态：** Finished

**文件：**
- 创建/移动：`agent/workflow/*`
- 删除：`agent/expression_workflow/binder.py`
- 修改：`agent/workflow/executor.py`
- 验证：`tests/test_workflow_*.py`

- 功能：通用层包含 core/context/executor/transition/capabilities，不再依赖 expression 命名。
- 实现说明：Runtime 直接调用 ContextAssembler 构造 StageContext，不再经过 Binder。
- 预期验证结果：通用 workflow tests 通过，代码中无 `StageInputBinder`。
- 完成时间：2026-09-15

## Phase #2: Expression 具体 workflow 包

### Task #2: 移动 Expression 专属模块

**状态：** Finished

**文件：**
- 创建/移动：`agent/workflows/expression/*`
- 修改：`agent/value_logic_generator.py`
- 验证：`python -m py_compile ...`

- 功能：Expression 只保留 definition/environment/handler/result_adapter/capabilities/failure_classifier。
- 实现说明：Expression factory 仍从 `agent.expression_generate_op.stages` 加载具体业务 Stage；通用 Stage 基类在 `agent.workflow.core.Stage`。
- 预期验证结果：Expression imports 指向新包；Harness 不依赖 Expression 内部 stage。
- 完成时间：2026-09-15

## Phase #3: 测试与兼容

### Task #3: 更新测试 imports

**状态：** Finished

**文件：**
- 修改：`tests/test_capability_layer.py`
- 修改：`tests/test_workflow_context_assembly.py`
- 修改：`tests/test_workflow_observations.py`
- 修改：`tests/test_workflow_recovery_loop.py`

- 功能：测试改用 `agent.workflow` 和 `agent.workflows.expression`。
- 预期验证结果：相关测试全部通过；baseline 缺失依赖如实记录。
- 完成时间：2026-09-15
