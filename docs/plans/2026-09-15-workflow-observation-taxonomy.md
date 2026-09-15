# Workflow Observation Taxonomy 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将 Workflow 中可识别业务失败结构化为 Runtime 可理解的 Observation，并为 Expression Workflow 提供稳定错误码分类。

**相关设计文档：** 当前用户需求，无独立批准设计文档。

**架构：** 在通用 workflow core 中增加 Observation / ObservationSeverity / StageResult.status，Runtime 对 failed StageResult 记录 observation 而不是依赖异常字符串。新增 ExpressionFailureClassifier，把 validator/resource/spec/generate 错误 deterministic 映射到 Observation。

**技术栈：** Python dataclass、现有 WorkflowRuntime / StageResult、pytest。

**范围 / 非范围：** 本轮覆盖结构化 Observation、错误码 taxonomy、Runtime 处理和可测试映射；不实现 LLM failure diagnosis，不重写当前缺失的 `agent.expression_generate_op` Stage 实现。

---

## Phase #1: Observation 模型

### Task #1: Runtime 可理解的 Observation

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/core.py`
- 修改：`agent/expression_workflow/executor.py`
- 验证：`tests/test_workflow_observations.py`

- 功能：定义 Observation 字段，StageResult 支持 `status="failed"` 和 `observation`。
- 实现说明：可恢复业务失败通过 StageResult 返回；Exception 仍保留给 IO、系统、编程、未预期错误。
- 预期验证结果：Runtime 遇到 failed result 时设置 state failed、记录 observation、保留 artifacts/trace。
- 完成时间：2026-09-15

## Phase #2: Expression FailureClassifier

### Task #2: Deterministic 错误映射

**状态：** Finished

**文件：**
- 创建：`agent/expression_workflow/failure_classifier.py`
- 验证：`tests/test_workflow_observations.py`

- 功能：定义 ExpressionObservationCode，并把 AST/resource/spec/generate 错误映射为 Observation。
- 实现说明：优先读取结构化 `error_type/code`；否则用保守关键词匹配。AST 覆盖 unknown property、unknown function、parameter mismatch、return type mismatch、syntax error。
- 预期验证结果：主要可恢复失败都有稳定 Observation.code。
- 完成时间：2026-09-15

## Phase #3: Expression 接入点

### Task #3: Definition/Adapter 使用 Observation

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/definition.py`
- 修改：`agent/expression_workflow/result_adapter.py`
- 验证：`python -m py_compile ...`

- 功能：Expression Stage metadata 绑定 failure classifier；validation_failed 输出带 observation 时适配现有 result。
- 实现说明：当前仓库缺 `agent.expression_generate_op.stages`，无法直接 patch 具体 Stage 类；先提供通用 classifier 与 runtime 支持，具体 Stage 只需返回 `StageResult(status="failed", observation=...)`。
- 预期验证结果：现有 structural/runtime tests 通过；baseline 缺失依赖如实记录。
- 完成时间：2026-09-15
