# Workflow Context Assembly 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 为现有 WorkflowRuntime 引入统一 Context Assembly，让所有 Expression Stage 输入都由统一 assembler 从 HarnessContext + WorkflowRunState 投影生成。

**相关设计文档：** 当前用户需求，无独立批准设计文档。

**架构：** 新增三层 Context 类型：HarnessContext 保存 session/project 级事实，WorkflowContext 从 HarnessContext 与 WorkflowRunState 派生，StageContext 是单个 Stage 的最小输入投影。WorkflowRuntime 调用 ContextAssembler 构建 Stage 输入，业务 Workflow 只声明每个 Stage 的 ContextPolicy。

**技术栈：** Python dataclass、现有 WorkflowDefinition / WorkflowRunState / Stage。

**范围 / 非范围：** 本轮实现 Context Projection、Context Dependency 声明、Expression 五个 Stage 的 ContextPolicy 与定向测试；不实现复杂语义检索，不改变资源在任务执行时读取最新文件的行为。

---

## Phase #1: Context 基础设施

### Task #1: 三层 Context 与 ContextPolicy

**状态：** Finished

**文件：**
- 创建：`agent/expression_workflow/context.py`
- 修改：`agent/expression_workflow/__init__.py`
- 验证：`tests/test_workflow_context_assembly.py`

- 功能：定义 HarnessContext、WorkflowContext、StageContext、ContextPolicy、ContextAssembler。
- 实现说明：StageContext 只暴露 policy 声明的数据；Assembler 从 workflow input、artifacts、harness facts、observations、execution history summary 中取值。
- 预期验证结果：测试证明 Stage 输入只包含声明字段，缺失必需依赖时抛错。
- 完成时间：2026-09-15

## Phase #2: Runtime 接入

### Task #2: Runtime 统一使用 ContextAssembler

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/executor.py`
- 修改：`agent/expression_workflow/binder.py`
- 验证：`tests/test_workflow_context_assembly.py`

- 功能：Runtime 在 `run_stage()` 中调用 assembler，而不是直接散落绑定逻辑。
- 实现说明：保留同步 API；接口以 `build(...)` 为主，当前实现为同步函数，内部不引入 async 复杂度。
- 预期验证结果：通用 workflow smoke 通过，Expression Runtime 边界不依赖业务域。
- 完成时间：2026-09-15

## Phase #3: Expression ContextPolicy

### Task #3: 五个 Stage 声明各自 ContextPolicy

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/definition.py`
- 修改：`agent/expression_workflow/environment.py`
- 验证：`python -m py_compile ...`

- 功能：为 spec_analysis、resource_search、expression_generate、ast_validation、finalize 设置最小 context 投影。
- 实现说明：SQL 分支传入的 `initial_filtered_env` 仍作为 workflow input/harness stage fact 投影到 ResourceSearchStage，不改变执行时读取最新资源文件的行为。
- 预期验证结果：Expression Stage 的输入全部经 ContextAssembler 生成；Stage 本身不直接读取 Harness 全局状态。
- 完成时间：2026-09-15

## Phase #4: 回归验证

### Task #4: baseline 与阻塞记录

**状态：** Finished

**文件：**
- 验证：`python -m py_compile ...`
- 验证：`.venv\Scripts\python.exe -m pytest tests/test_workflow_context_assembly.py -q`
- 验证：`.venv\Scripts\python.exe -m pytest tests/test_value_logic_generator.py -q`

- 功能：确认 Context Assembly 自测通过，并记录当前业务版 baseline 是否仍受缺失模块影响。
- 实现说明：不为通过测试而回滚用户业务改动；如当前仓库缺依赖，明确报告导入阻塞。
- 预期验证结果：新增测试通过；baseline 若失败，错误定位到现有缺失依赖。
- 完成时间：2026-09-15
