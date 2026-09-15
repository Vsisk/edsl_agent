# Expression Workflow 控制权抽离 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将 Expression Workflow 的固定 Stage 顺序、输入绑定、执行控制和结果适配从 `ValueLogicGenerator` 中抽离。

**相关设计文档：** 用户本轮 Round 3 请求文本（`C:\Users\Vsisk\.codex\attachments\97e4c24c-5618-4680-95fb-2c707cc041b5\pasted-text.txt`）

**架构：** 新增 `agent/expression_workflow/`，内部包含 `ExpressionExecutionEnvironment`、Stage/State 基础模型、Stage 实现、WorkflowDefinition、StageInputBinder、LinearWorkflowExecutor、ResultAdapter 和 Handler。`ValueLogicGenerator` 只构造环境并调用 Handler，保留非 expression 分支和 legacy whole-workflow retry wrapper。

**技术栈：** Python、dataclasses、Pydantic 模型、pytest。

**范围 / 非范围：** 本轮只抽离 Expression Workflow 控制权；不实现动态 retry、回边、TransitionPolicy、FailureDiagnoser 或 Handler Registry。

---

## Phase #1: 工作流模块落地

### Task #1: 新增 Stage/State/Signal 基础设施

**状态：** Finished

**文件：**
- 创建：`agent/expression_workflow/core.py`
- 创建：`agent/expression_workflow/environment.py`
- 创建：`agent/expression_workflow/__init__.py`

- 功能：提供 `WorkflowRunState`、`WorkflowStatus`、`StageSignal`、`StageResult`、`execute_stage` 和 `ExpressionExecutionEnvironment`。
- 实现说明：基础设施不依赖 `ValueLogicGenerator`，`WorkflowRunState` 是中间 artifact 唯一来源。
- 预期验证结果：模块可导入，状态和 artifact 写读工作正常。

### Task #2: 新增 Stage 实现与绑定声明

**状态：** Finished

**文件：**
- 创建：`agent/expression_workflow/stages.py`

- 功能：实现五个 Stage 及对应 typed input，并在 Stage 上声明 `artifact_bindings` 与 `environment_bindings`。
- 实现说明：Stage 只读 typed input，不直接访问 `WorkflowRunState`；OOTB/validation failed 通过 `StageSignal` 上报。
- 预期验证结果：Stage 输出 artifact key 与原 pipeline 行为一致。

## Phase #2: Definition/Executor/Handler

### Task #3: 新增通用 Binder 和线性 Executor

**状态：** Finished

**文件：**
- 创建：`agent/expression_workflow/binder.py`
- 创建：`agent/expression_workflow/executor.py`
- 创建：`agent/expression_workflow/definition.py`

- 功能：由 Definition 拥有固定顺序，由 Binder 自动投影 state/environment 到 Stage input，由 Executor 执行并处理 terminal signal。
- 实现说明：Binder 不知道具体业务类型；Executor 不实现动态回边。
- 预期验证结果：五段 workflow 可按定义顺序执行，terminal 状态写回 state。

### Task #4: 新增 ResultAdapter 和 Handler

**状态：** Finished

**文件：**
- 创建：`agent/expression_workflow/result_adapter.py`
- 创建：`agent/expression_workflow/handler.py`

- 功能：Handler 是 expression workflow 唯一入口；ResultAdapter 将最终 state 转成 `ValueLogicResult`。
- 实现说明：支持 final success、OOTB、validation failed；`ValueLogicGenerator` 不读内部 artifact。
- 预期验证结果：结果形态与原 expression path 一致。

## Phase #3: 生成器接入与清理

### Task #5: 收缩 ValueLogicGenerator 职责

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`

- 功能：删除 `_run_expression_attempt()` 和旧的第二套 expression pipeline；`_generate_expression_attempt()` 只构造 `ExpressionExecutionEnvironment` 并调用 Handler。
- 实现说明：保留 whole-workflow retry wrapper，并添加 Round 4 替换注释；保留 SQL/summary/table field 分支。
- 预期验证结果：`ValueLogicGenerator` 不再引用 StageContext、`execute_stage`、`WorkflowRunState`。

### Task #6: 验证 baseline

**状态：** Finished

**文件：**
- 验证：`tests/test_value_logic_generator.py`
- 验证：全量 `pytest`

- 功能：确认 expression 行为和原 baseline 一致。
- 实现说明：先跑定向测试，再跑全量测试；如外部资源导致失败，记录具体失败。
- 预期验证结果：baseline 测试通过，或剩余失败有明确非本轮原因。
