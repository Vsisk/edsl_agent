# Move Workflow Implementations 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将 Value Logic 父 workflow 与 SQL / BO Field child workflow 的实现体从旧 `agent.workflows.value_logic` 迁移到新 `agent.workflow.value_logic` 目录。

**相关设计文档：** 用户要求的目标目录结构。

**架构：** 新目录承载实现体，旧目录只保留兼容 re-export。父 workflow 实现位于 `agent.workflow.value_logic`，SQL / BO Field child workflow 实现位于 `agent.workflow.value_logic.branches`，公共 BranchOutcome 位于 `agent.workflow.value_logic.result`。

**技术栈：** Python dataclass、现有 WorkflowDefinition / WorkflowRuntime / ContextPolicy。

**范围 / 非范围：** 本轮迁移 Value Logic 相关实现体；通用 runtime 物理拆分和 Expression 内部 stage 实现体后续继续迁移；不重写 SQL / BO / Expression 业务算法。

---

## Phase #1: Value Logic 实现体迁移

### Task #1: Outcome / Environment / Handler

**状态：** Finished

**文件：**
- 修改：`agent/workflow/value_logic/result.py`
- 修改：`agent/workflow/value_logic/models.py`
- 修改：`agent/workflow/value_logic/handler.py`
- 修改：`agent/workflows/value_logic/outcome.py`
- 修改：`agent/workflows/value_logic/environment.py`
- 修改：`agent/workflows/value_logic/handler.py`
- 验证：`tests/test_workflow_directory_layout.py`

- 功能：新目录持有 ValueLogicBranchOutcome、ValueLogicExecutionEnvironment、ValueLogicWorkflowHandler 实现。
- 实现说明：旧目录仅 re-export。
- 预期验证结果：导出类的 `__module__` 指向 `agent.workflow.value_logic`。

### Task #2: Parent stages / definition

**状态：** Finished

**文件：**
- 修改：`agent/workflow/value_logic/stages/*.py`
- 修改：`agent/workflow/value_logic/definition.py`
- 修改：`agent/workflows/value_logic/stages.py`
- 修改：`agent/workflows/value_logic/definition.py`
- 验证：`tests/test_value_logic_workflow.py`

- 功能：父 ValueLogicWorkflow 的 prepare/route/invoke/handle/finalize 实现体迁入新目录。
- 实现说明：旧文件 re-export，避免旧调用方立即断裂。
- 预期验证结果：父子 workflow 测试通过。

## Phase #2: Branch child workflow 实现体迁移

### Task #3: SQL / BO Field branch implementations

**状态：** Finished

**文件：**
- 修改：`agent/workflow/value_logic/branches/sql/*`
- 修改：`agent/workflow/value_logic/branches/bo_field/*`
- 修改：`agent/workflows/value_logic/child_workflows.py`
- 验证：`tests/test_workflow_directory_layout.py`

- 功能：SQL / BO Field 单 stage child workflow 实现体迁入新目录。
- 实现说明：Expression adapter 仍复用现有 ExpressionWorkflow 入口。
- 预期验证结果：SQL / BO Field child workflow factory 的 `__module__` 指向新目录。

## Phase #3: 回归

### Task #4: 定向验证

**状态：** Finished

**文件：**
- 验证：`tests/test_workflow_directory_layout.py`
- 验证：`tests/test_harness_runtime.py`
- 验证：`tests/test_value_logic_workflow.py`
- 验证：workflow 相关测试组

- 功能：验证新目录实现体可用，旧路径兼容，行为不变。
- 实现说明：baseline 若仍受既有依赖阻塞，需要明确说明。
- 预期验证结果：定向测试通过。
