# Workflow Target Directory Layout 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 按用户设定目录，将通用 Workflow Runtime 与 Value Logic 父子 Workflow 暴露到 `agent/workflow/runtime` 和 `agent/workflow/value_logic` 目标结构。

**相关设计文档：** 用户本轮关于目标目录结构的说明。

**架构：** 采用渐进式迁移：新目录成为正式 import 入口，旧 `agent.workflow.*` 与 `agent.workflows.*` 暂作为兼容实现层，避免一次性破坏现有调用。ValueLogic 父 Workflow 位于 `agent.workflow.value_logic`，SQL / BO Field / Expression child workflow 位于 `agent.workflow.value_logic.branches`。

**技术栈：** Python package re-export、现有 WorkflowRuntime / WorkflowDefinition / ValueLogicWorkflowFactory。

**范围 / 非范围：** 本轮完成目录骨架和正式入口迁移；不重写 SQL / BO / Expression 内部算法；不强制删除所有旧路径，旧路径后续可逐步物理搬迁或降级为兼容转发。

---

## Phase #1: 通用 Runtime 目录

### Task #1: Runtime module entrypoints

**状态：** Finished

**文件：**
- 创建：`agent/workflow/runtime/__init__.py`
- 创建：`agent/workflow/runtime/definition.py`
- 创建：`agent/workflow/runtime/runtime.py`
- 创建：`agent/workflow/runtime/run_state.py`
- 创建：`agent/workflow/runtime/stage.py`
- 创建：`agent/workflow/runtime/stage_result.py`
- 创建：`agent/workflow/runtime/stage_input_binder.py`
- 创建：`agent/workflow/runtime/subworkflow.py`
- 验证：`tests/test_workflow_directory_layout.py`

- 功能：按目标目录暴露 Definition、Runtime、RunState、Stage、StageResult、Subworkflow。
- 实现说明：`stage_input_binder.py` 显式映射到 ContextAssembler，避免恢复旧 Binder 边界。
- 预期验证结果：新 runtime 目录所有核心类型可导入。

## Phase #2: Value Logic 父 Workflow 目录

### Task #2: Parent workflow package

**状态：** Finished

**文件：**
- 创建：`agent/workflow/value_logic/__init__.py`
- 创建：`agent/workflow/value_logic/definition.py`
- 创建：`agent/workflow/value_logic/factory.py`
- 创建：`agent/workflow/value_logic/input.py`
- 创建：`agent/workflow/value_logic/result.py`
- 创建：`agent/workflow/value_logic/models.py`
- 创建：`agent/workflow/value_logic/context_assembler.py`
- 创建：`agent/workflow/value_logic/handler.py`
- 验证：`tests/test_workflow_directory_layout.py`

- 功能：建立 ValueLogicWorkflow 的目标目录主入口。
- 实现说明：复用现有实现层，新增明确 WorkflowInput / Result / ContextAssembler 入口。
- 预期验证结果：Harness 和 ValueLogic tests 通过新目录导入。

## Phase #3: Value Logic stages 与 branches

### Task #3: Stages and child workflow branch packages

**状态：** Finished

**文件：**
- 创建：`agent/workflow/value_logic/stages/*.py`
- 创建：`agent/workflow/value_logic/branches/expression/*.py`
- 创建：`agent/workflow/value_logic/branches/sql/*.py`
- 创建：`agent/workflow/value_logic/branches/bo_field/*.py`
- 验证：`tests/test_workflow_directory_layout.py`

- 功能：按目标目录表达 prepare/route/invoke/finalize，以及 expression/sql/bo_field child workflow。
- 实现说明：Expression stage 模块先作为命名入口，不复制内部业务实现。
- 预期验证结果：父子 workflow 新目录入口可导入。

## Phase #4: Import 迁移与回归

### Task #4: Official imports use target package

**状态：** Finished

**文件：**
- 修改：`tests/test_harness_runtime.py`
- 修改：`tests/test_value_logic_workflow.py`
- 修改：`agent/value_logic_generator.py`
- 验证：workflow 相关测试组

- 功能：将正式测试和 legacy adapter 的 ValueLogic import 切到 `agent.workflow.value_logic`。
- 实现说明：旧 `agent.workflows.value_logic` 保留为实现兼容路径。
- 预期验证结果：`33 passed`，py_compile 通过。
