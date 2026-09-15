# Global Harness Runtime 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 构建 Global Harness，使用户级请求路由到 Workflow 级能力，Harness 不理解 Expression Workflow 内部 Stage。

**相关设计文档：** 当前用户需求，无独立批准设计文档。

**架构：** 新增 `agent/harness` 包。HarnessRuntime 管 OperationPlan 和 workflow 依赖执行；WorkflowRegistry 管 workflow metadata 与 adapter；RequirementAnalyzer 从用户 query 生成 workflow 级 operation；WorkflowRouter 只选择 workflow 能力，不规划 workflow 内部 stage。现有能力通过 LegacyWorkflowAdapter 接入，Expression 通过 ExpressionWorkflowAdapter 接入。

**技术栈：** Python dataclass、现有 operation 类、现有 Expression Workflow/ValueLogicGenerator 入口、pytest。

**范围 / 非范围：** 第一版真正迁移 expression_generation 的 harness 入口；node_generation/node_modify/ab_data_source_generation/pdf_parse/excel_parse 先注册 metadata，可用 LegacyWorkflowAdapter 接入。暂不删除旧 API/WebSocket 路径。

---

## Phase #1: Harness 核心模型

### Task #1: HarnessContext / OperationPlan / Registry

**状态：** Finished

**文件：**
- 创建：`agent/harness/models.py`
- 创建：`agent/harness/registry.py`
- 创建：`agent/harness/adapters.py`
- 创建：`agent/harness/__init__.py`
- 验证：`tests/test_harness_runtime.py`

- 功能：定义 HarnessContext、Operation、OperationPlan、WorkflowMetadata、WorkflowRegistry 和 WorkflowAdapter 协议。
- 实现说明：Operation 包含 op_id/query/workflow/input/depends_on/status/result_ref；Registry 只暴露 workflow metadata 与 adapter，不暴露 stage。
- 预期验证结果：注册重复 workflow 报错；metadata 可列出已注册 workflow。
- 完成时间：2026-09-15

## Phase #2: Analyzer / Router / Runtime

### Task #2: 用户请求到 workflow operation plan

**状态：** Finished

**文件：**
- 创建：`agent/harness/analyzer.py`
- 创建：`agent/harness/router.py`
- 创建：`agent/harness/runtime.py`
- 验证：`tests/test_harness_runtime.py`

- 功能：RequirementAnalyzer 解析用户 query，WorkflowRouter 生成 OperationPlan，HarnessRuntime 按依赖顺序执行。
- 实现说明：第一版 deterministic keyword/rule；“新增...字段，并生成...取值逻辑” 生成 node_generation -> expression_generation 两个 operation。
- 预期验证结果：多 workflow 示例得到两个 operation 且第二个依赖第一个；执行时按依赖顺序。
- 完成时间：2026-09-15

## Phase #3: Workflow 接入

### Task #3: Expression 与 Legacy adapter

**状态：** Finished

**文件：**
- 修改：`agent/harness/adapters.py`
- 创建：`agent/harness/defaults.py`
- 验证：`tests/test_harness_runtime.py`

- 功能：ExpressionWorkflowAdapter 调用注入的 expression handler/generator；LegacyWorkflowAdapter 包装现有 operation callable。
- 实现说明：默认注册 expression_generation、node_generation、node_modify、ab_data_source_generation、pdf_parse、excel_parse；未注入实现的 legacy workflow 返回明确 unsupported。
- 预期验证结果：HarnessRuntime.handle() 可路由单条 expression 请求到 expression_generation adapter；多 workflow 请求不暴露 Expression 内部 stage。
- 完成时间：2026-09-15

## Phase #4: API 兼容入口

### Task #4: 保留旧入口并暴露 Harness handle

**状态：** Finished

**文件：**
- 创建：`agent/harness/api.py`
- 验证：`tests/test_harness_runtime.py`

- 功能：提供 `handle_harness_request()` 作为 API/WebSocket 逐步统一入口；不删除旧 API。
- 实现说明：只新增兼容函数，不强制改现有服务器路径，避免一次性迁移风险。
- 预期验证结果：测试可通过该入口执行 expression workflow。
- 完成时间：2026-09-15
