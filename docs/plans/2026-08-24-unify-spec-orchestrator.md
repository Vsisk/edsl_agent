# 统一 SpecOrchestrator 生成链路实现计划

> **给 Claude：** 使用 `test-driven-development` 逐任务实现此计划。

**目标：** 删除独立 `agent/expression_spec` 轻量链路，只保留现有 `SpecOrchestrator + ResolutionCompiler` 作为唯一 Spec 生成系统，并补齐 Requirement/Goal 复用能力。

**相关设计文档：** 本轮讨论；`docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** 现有 `ValueGoal` 继续承担 Requirement 角色，`GoalSearchRequest` 继续承担 searchRequirement 角色，`OrchestratorResourceSearch` 负责资源搜索，`SpecOrchestrator` 内部维护闭合 registry，`ResolutionCompiler` 继续输出 `ExpressionSpec.nl` 与 `FilteredEnvironment`。不再保留 `agent/expression_spec` 作为第二套 spec 生成系统。

**技术栈：** Python、Pydantic v2、pytest。

**范围 / 非范围：** 本次删除独立轻量模块与测试，增强现有 orchestrator 的已解析目标复用；不引入新的公开 spec 系统，不改 Planner。

---

## Phase #1: 删除第二套 Spec 系统

### Task #1: 移除独立 expression_spec 包

**状态：** Designed

**文件：**
- 删除：`agent/expression_spec/`
- 删除：`tests/test_expression_spec_lightweight.py`
- 删除：`docs/plans/2026-08-24-expression-spec-lightweight.md`
- 验证：`rg -n "agent.expression_spec|ExpressionSpecWorkflow|SearchRequestGenerator|ResourceSearchService" agent tests docs`

**功能：** 确保系统中不存在第二套 spec 生成入口。

**实现说明：** 保留 `agent/expression_generation/expression_spec.py`，它是 Planner 输入模型与 skill scope，不是被删除对象。

**预期验证结果：** 搜索不到独立 `agent.expression_spec` 引用；现有 Planner 的 `ExpressionSpec` 模型仍保留。

## Phase #2: SpecOrchestrator Registry 复用

### Task #2: 解析结果 registry

**状态：** Designed

**文件：**
- 修改：`agent/spec_orchestration/orchestrator.py`
- 验证：`tests/test_spec_orchestrator.py`

**功能：** 在单次 `resolve()` 内维护已闭合 goal registry；当后续 Requirement/Goal 需要同一语义值和类型时，直接复用已闭合结果，不重复搜索。

**实现说明：** 以 goal 语义名、期望类型名、是否列表作为复用签名；在 commit 后注册 resolved goal；依赖绑定使用实际复用到的 goal id。

**预期验证结果：** 两个 NamingSQL 参数需要同一个 ID 时只搜索一次 ID，两个参数都绑定到同一个已解析 Requirement。

### Task #3: Requirement-as-resource 编译验证

**状态：** Designed

**文件：**
- 修改：`tests/test_spec_orchestrator_compiler.py`

**功能：** 验证某个 Requirement 的结果作为另一个资源参数时，`ResolutionCompiler` 生成的 NL 能描述该绑定，并且资源被加入现有 `FilteredEnvironment`。

**实现说明：** 使用现有 `ResolvedGoal.bindings` 与依赖树，不新增输出模型。

**预期验证结果：** 编译结果包含参数绑定文本、参数来源 context、NamingSQL 所属 BO 和 selection。

## Phase #3: 回归验证

### Task #4: 定向回归

**状态：** Designed

**文件：**
- 验证：`.\.venv\Scripts\python.exe -m pytest tests/test_spec_orchestrator_models.py tests/test_spec_orchestrator.py tests/test_spec_orchestrator_search.py tests/test_spec_orchestrator_compiler.py tests/test_spec_orchestrator_semantic.py tests/test_value_logic_generator.py tests/test_expression_spec.py -q`

**功能：** 确认唯一 spec 生成链路仍能输出 NL 与 FilteredEnvironment，且 value logic 主链没有退回旧系统。

**实现说明：** 若历史编码文本导致断言显示乱码，以实际测试结果为准，不顺手修复无关文本。

**预期验证结果：** 定向测试通过；无 `agent.expression_spec` 残留引用。
