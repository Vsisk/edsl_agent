# Harness Direct Value Logic Workflow 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 将 Harness 的正式 Value Logic 执行入口从 `ValueLogicGenerator.generate()` / callback facade 切换为 `WorkflowRegistry -> WorkflowRuntime -> ValueLogicWorkflow`。

**相关设计文档：** 用户本轮粘贴的 Agent Harness 架构重构说明。

**架构：** 保留现有 Harness / Workflow 包结构，不为目录名做破坏性迁移；新增通用 WorkflowRuntime adapter，让 Harness registry 可以注册 `WorkflowDefinition` factory 并直接运行。ValueLogicWorkflow 继续负责 branch-level orchestration，SQL / BO Field / Expression 作为 internal child workflow。

**技术栈：** Python dataclass、现有 HarnessRuntime / WorkflowRegistry / WorkflowRuntime / WorkflowDefinition。

**范围 / 非范围：** 本轮迁移 Harness 主路径和 registry contract；不重写 SQL、BO、Expression 内部算法；`ValueLogicGenerator` 暂保留为 deprecated legacy adapter 以避免破坏现有外部测试和调用方，但不得作为 Harness 默认正式入口。

---

## Phase #1: Harness 注册模型

### Task #1: Workflow metadata visibility

**状态：** Finished

**文件：**
- 修改：`agent/harness/models.py`
- 修改：`agent/harness/defaults.py`
- 验证：`tests/test_harness_runtime.py`

- 功能：WorkflowMetadata 增加 public/internal visibility，ValueLogic public，Expression/SQL/BO internal。
- 实现说明：保留 legacy 字段兼容现有代码。
- 预期验证结果：Harness 普通路由仍只选择 `value_logic_generation`。

### Task #2: Runtime-backed workflow adapter

**状态：** Finished

**文件：**
- 修改：`agent/harness/adapters.py`
- 修改：`agent/harness/defaults.py`
- 修改：`agent/harness/api.py`
- 验证：`tests/test_harness_runtime.py`

- 功能：Harness registry 可注册 `WorkflowDefinition` factory，通过 `WorkflowRuntime` 直接执行。
- 实现说明：adapter 负责 Operation input 映射、environment 构建、RunState 创建和 `final_result` 读取。
- 预期验证结果：不传 `value_logic_execute` callback 时，仍可通过 factory 执行 ValueLogicWorkflow。

## Phase #2: Value Logic Workflow 注册

### Task #3: 注册 ValueLogicWorkflow 与 internal child metadata

**状态：** Finished

**文件：**
- 修改：`agent/harness/defaults.py`
- 验证：`tests/test_harness_runtime.py`

- 功能：默认 registry 注册 public `value_logic_generation`，并注册 internal `expression_generation`、`sql_value_logic_generation`、`bo_field_value_logic_generation`。
- 实现说明：child workflow 普通业务不直接运行，metadata 用于可观测性与架构边界。
- 预期验证结果：Registry metadata 中 visibility 正确。

## Phase #3: Legacy 入口降级

### Task #4: 标记 ValueLogicGenerator 为 deprecated legacy adapter

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`
- 验证：`rg` 全局搜索

- 功能：明确 `ValueLogicGenerator` 不再是 Harness 主路径。
- 实现说明：保留现有兼容入口，但新增 deprecation 标记与注释；Harness 默认注册不依赖它。
- 预期验证结果：Harness 代码不引用 `ValueLogicGenerator`。

## Phase #4: 验证

### Task #5: 定向回归

**状态：** Finished

**文件：**
- 验证：`tests/test_harness_runtime.py`
- 验证：`tests/test_value_logic_workflow.py`
- 验证：workflow/context/capability/recovery 相关测试

- 功能：证明 Harness 直连 ValueLogicWorkflow 与父子 workflow 结构仍通过。
- 实现说明：baseline 若仍受既有缺失依赖阻塞，明确报告。
- 预期验证结果：新增和既有定向测试通过。
