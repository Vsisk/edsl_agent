# Workflow DAG Recovery Loop 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将固定 pipeline 升级为 deterministic 有向执行图，并支持 Expression Workflow 的自动恢复回边。

**相关设计文档：** 当前用户需求，无独立批准设计文档。

**架构：** 在通用 workflow 层增加 TransitionPolicy、RetryPolicy、LoopGuard。Runtime 每次 Stage 结束后根据 StageResult/Observation 选择下一跳，并由 LoopGuard 限制总 transition、单 stage retry、相同失败 fingerprint 和相同 artifact fingerprint。ContextAssembler 从 WorkflowRunState 构造 downstream feedback，供二次进入 Stage 时 refine 使用。

**技术栈：** Python dataclass、现有 WorkflowRuntime / WorkflowRunState / ContextAssembler、pytest。

**范围 / 非范围：** 本轮只实现 deterministic transition，不引入 LLM Transition Planner；端到端测试使用 fake Expression stages 验证自动恢复 loop。

---

## Phase #1: Transition / Retry / LoopGuard

### Task #1: 通用执行图模型

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/core.py`
- 创建：`agent/expression_workflow/transition.py`
- 修改：`agent/expression_workflow/executor.py`
- 验证：`tests/test_workflow_recovery_loop.py`

- 功能：定义 TransitionRule、TransitionPolicy、RetryPolicy、LoopGuard，并让 Runtime 根据 Observation.code 决定下一 stage。
- 实现说明：默认 transition 仍兼容现有线性流；有 rule 命中时允许回边；LoopGuard 记录 transition trace 与 fingerprint。
- 预期验证结果：failed result 不再必然终止，retryable observation 可触发 deterministic 回边。
- 完成时间：2026-09-15

## Phase #2: ContextAssembler downstream feedback

### Task #2: 二次进入 Stage 的反馈投影

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/context.py`
- 修改：`agent/expression_workflow/core.py`
- 验证：`tests/test_workflow_recovery_loop.py`

- 功能：构造 `downstream_feedback`，包含 validation error、generated expression、missing property/type、previous selected resources/candidates、rejected resource ids 等。
- 实现说明：StageContext/ContextPolicy 支持按字段注入 downstream feedback；默认不泄漏完整 RunState。
- 预期验证结果：第二次进入 resource_search 时输入包含第一次错误反馈。
- 完成时间：2026-09-15

## Phase #3: Expression Workflow 回边

### Task #3: 配置 Expression deterministic transitions

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/definition.py`
- 验证：`tests/test_workflow_recovery_loop.py`

- 功能：配置 validate/generate/resource_search/spec 的回边规则。
- 实现说明：validate 的 syntax/function 回 generate；unknown property/type mismatch 回 resource_search；resource_search 的 spec insufficient 回 spec；generate 的 resource not found 回 resource_search。
- 预期验证结果：fake workflow 完整 trace 为 resource_search -> generate -> validate -> resource_search -> generate -> validate -> finalize。
- 完成时间：2026-09-15

## Phase #4: 验证

### Task #4: 回归与 baseline

**状态：** Finished

**文件：**
- 验证：`python -m py_compile ...`
- 验证：`.venv\Scripts\python.exe -m pytest tests/test_workflow_recovery_loop.py tests/test_workflow_observations.py tests/test_capability_layer.py tests/test_workflow_context_assembly.py -q`
- 验证：`.venv\Scripts\python.exe -m pytest tests/test_value_logic_generator.py -q`

- 功能：确认 DAG recovery loop 可工作，并记录当前业务 baseline 状态。
- 实现说明：不修复当前业务版缺失模块，除非属于本轮 Runtime 边界。
- 预期验证结果：新增 DAG 测试通过；baseline 如仍缺 `agent.agent_runner` 则如实记录。
- 完成时间：2026-09-15
