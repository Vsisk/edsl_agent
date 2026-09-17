# Workflow 包边界统一实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将 `agent.workflow` 收敛为纯通用框架层，并将 Value Logic 的真实业务实现统一迁移到 `agent.workflows.value_logic`。

**相关设计文档：** 无单独设计文档；以当前对话已确认的 `workflow` 通用层、`workflows` 业务层边界为准。

**架构：** `agent.workflow` 仅提供 Runtime、Context、Capability、Transition 等领域无关机制；`agent.workflows` 提供 Value Logic、Expression 等具体工作流。Harness 和业务入口依赖具体 Workflow，具体 Workflow 单向依赖通用 Runtime。

**技术栈：** Python、pytest、现有 WorkflowRuntime/Harness 实现。

**范围 / 非范围：** 迁移 Value Logic 实现、更新导入、移除旧兼容入口并验证行为；不改动 Value Logic 的路由、分支策略和生成逻辑，不纳入当前工作区已有的资源类型与 loader 修改。

---

## Phase #1: 锁定包边界

### Task #1: 增加目录边界回归测试

**状态：** Finished

**文件：**
- 修改：`tests/test_workflow_directory_layout.py`
- 验证：`tests/test_workflow_directory_layout.py`

- 功能：明确 Value Logic 的实现模块属于 `agent.workflows.value_logic`，且通用层不存在具体 Value Logic 包。
- 实现说明：通过实现类所属模块和源码目录存在性验证边界，先观察测试因当前布局失败。
- 预期验证结果：迁移前测试稳定失败，失败原因指向 Value Logic 仍位于通用层。

## Phase #2: 迁移业务实现

### Task #2: 将 Value Logic 实现迁入具体 Workflow 层

**状态：** Finished

**文件：**
- 移动：`agent/workflow/value_logic/` 到 `agent/workflows/value_logic/`
- 修改：`agent/value_logic_generator.py`
- 修改：Value Logic 包内所有绝对导入
- 修改：相关测试导入

- 功能：让 Value Logic 父 Workflow、Stage、Context Assembler 以及 SQL/BO Field/Expression 分支都由具体 Workflow 包拥有。
- 实现说明：保留现有行为和公开对象名称，只切换唯一真实实现位置；删除原转发壳和通用层中的业务包。
- 预期验证结果：目录边界测试转绿，仓库中不再引用 `agent.workflow.value_logic`。

## Phase #3: 回归与清理

### Task #3: 验证依赖方向和基线行为

**状态：** Finished

**文件：**
- 验证：`tests/test_workflow_directory_layout.py`
- 验证：`tests/test_value_logic_workflow.py`
- 验证：`tests/test_harness_runtime.py`
- 验证：Expression Workflow、Context、Observation、Recovery 相关测试

- 功能：确认 Harness 仍能调用 Value Logic，三个分支和 Expression 子 Workflow 行为不变。
- 实现说明：检查旧导入残留、差异格式、语法编译和定向 pytest；保留无关工作区修改。
- 预期验证结果：相关测试全部通过，`agent.workflow` 不依赖 `agent.workflows`，且不存在旧 Value Logic 入口。
