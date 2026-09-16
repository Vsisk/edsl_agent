# Value Logic Child Workflows 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将 Value Logic 建模为 Harness 可见父 Workflow，并将 SQL / BO Field / Expression 建模为独立 Child Workflow，由父 Workflow 统一管理 branch routing、fallback 和最终结果。

**相关设计文档：** 用户本轮粘贴的 Harness / Workflow Runtime 架构重构说明。

**架构：** 在通用 WorkflowRunState 上补充 run_id 与 parent_run_id，并在 WorkflowRuntime 上提供 child workflow invocation。ValueLogicWorkflow 只保存 branch-level artifact；SQLWorkflow、BOFieldWorkflow、ExpressionWorkflow 各自拥有独立 WorkflowRunState，并通过 ValueLogicBranchOutcome 向父 Workflow 返回统一结果。

**技术栈：** Python dataclass、现有 WorkflowRuntime / WorkflowDefinition / Stage / ContextAssembler。

**范围 / 非范围：** 本轮采用 adapter 式迁移，不重写 SQL、BO、Expression 内部业务算法；Summary 暂时保留在 ValueLogicWorkflow 内部 Stage；不实现复杂 LLM routing 或全局 Planner。

---

## Phase #1: Runtime 父子 Run 支撑

### Task #1: WorkflowRunState 运行关系

**状态：** Finished

**文件：**
- 修改：`agent/workflow/core.py`
- 修改：`agent/workflow/executor.py`
- 验证：`tests/test_value_logic_workflow.py`

- 功能：为每个 WorkflowRunState 增加 run_id / parent_run_id，并提供通用 child workflow invocation。
- 实现说明：run_id 自动生成，child run 必须独立创建 state，不能复用 parent state。
- 预期验证结果：子 workflow 的 parent_run_id 等于父 ValueLogic run_id。

## Phase #2: Branch Outcome 与 Child Workflow

### Task #2: 统一 ValueLogicBranchOutcome

**状态：** Finished

**文件：**
- 创建：`agent/workflows/value_logic/outcome.py`
- 修改：`agent/workflows/value_logic/__init__.py`
- 验证：`tests/test_value_logic_workflow.py`

- 功能：SQL / BO Field / Expression 统一输出 success / fallback / failed / need_user_input / escalate。
- 实现说明：fallback 使用 fallback_target 与 handoff_artifacts，不允许 sibling workflow 直接互调。
- 预期验证结果：SQL / BO fallback 后，父 workflow 接收 outcome 并决定下一 branch。

### Task #3: SQL / BO / Expression Child Workflow Adapter

**状态：** Finished

**文件：**
- 创建：`agent/workflows/value_logic/child_workflows.py`
- 修改：`agent/workflows/value_logic/definition.py`
- 验证：`tests/test_value_logic_workflow.py`

- 功能：将现有 SQL / BO / Expression 能力包装为独立 child workflow。
- 实现说明：SQL / BO 内部失败时只返回 fallback outcome；Expression 返回 success / failed outcome。
- 预期验证结果：SQL fallback Expression、BO fallback Expression 都由父 workflow 驱动。

## Phase #3: ValueLogicWorkflow 父编排

### Task #4: 父 Workflow Definition 重组

**状态：** Finished

**文件：**
- 修改：`agent/workflows/value_logic/stages.py`
- 修改：`agent/workflows/value_logic/definition.py`
- 修改：`agent/workflows/value_logic/handler.py`
- 验证：`tests/test_value_logic_workflow.py`

- 功能：ValueLogicWorkflow 变为 prepare / route / invoke_branch / handle_outcome / finalize。
- 实现说明：父 state 只保存 target、branch、branch_history、child_run_id、branch_outcome、handoff_artifacts、final_result。
- 预期验证结果：重复 fallback 到已访问 branch 时停止，防止 branch loop。

## Phase #4: ValueLogicGenerator 收缩

### Task #5: 删除 sibling direct fallback

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`
- 验证：`tests/test_value_logic_workflow.py`

- 功能：ValueLogicGenerator 不再由 SQL / BO 方法直接调用 Expression 分支。
- 实现说明：保留兼容方法时改为 adapter，不作为主路径 branch pipeline。
- 预期验证结果：主路径通过 ValueLogicWorkflow 调用 child workflow，branch fallback 由父 workflow 控制。

## Phase #5: 回归验证

### Task #6: 定向测试与 baseline

**状态：** Finished

**文件：**
- 验证：`tests/test_value_logic_workflow.py`
- 验证：`tests/test_harness_runtime.py`
- 验证：`tests/test_workflow_recovery_loop.py`
- 验证：`tests/test_workflow_observations.py`
- 验证：`tests/test_capability_layer.py`
- 验证：`tests/test_workflow_context_assembly.py`

- 功能：验证父子 workflow、fallback、Harness 路由和现有 workflow 能力。
- 实现说明：baseline 如仍因既有缺失依赖失败，需要明确报告。
- 预期验证结果：新增路径测试通过；已知 baseline 阻塞原因清晰。
