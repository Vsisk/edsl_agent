# Goal 搜索策略参数化重构计划

> **给 Codex：** 按本计划使用测试驱动开发完成实现。

**目标：** 每次 Goal 求解都必须显式传入允许的资源搜索策略，严格区分 Value Goal 与 BO Goal。

**相关设计文档：** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** Value Policy 固定为 Context、BO field、Function、Literal；BO Access Policy 固定为 NamingSQL、Select。Root、NamingSQL 参数、Function 参数和 Select 条件均使用 Value Policy；BO field 创建的 BO Goal 使用 BO Access Policy。

**技术栈：** Python、Pydantic、pytest

**范围 / 非范围：** 重构 Orchestrator 搜索策略输入、Literal 候选与结果编译；不修改公开 ValueLogicResult，不触碰当前工作区已有的 TypedContext/Planner 未提交改动。

---

## Phase #1: 显式搜索策略

### Task #1: 移除隐式全量搜索

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/models.py`
- 修改：`agent/spec_orchestration/orchestrator.py`
- 验证：`tests/test_spec_orchestrator.py`
- 功能：每次 Goal 求解必须传入允许资源层集合。
- 实现说明：Root 和所有参数/条件 Goal 使用 Value Policy；BO Goal 使用 BO Access Policy；不存在默认全量策略。
- 预期验证结果：不同 Goal 的搜索调用严格等于各自策略，不能越权进入其他层。

## Phase #2: Literal 兜底

### Task #2: 增加纯字符串候选

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/search.py`
- 修改：`agent/spec_orchestration/compiler.py`
- 验证：`tests/test_spec_orchestrator_search.py`
- 验证：`tests/test_spec_orchestrator_compiler.py`
- 功能：字符串 Value Goal 在真实资源均不覆盖时可进入纯字符串候选。
- 实现说明：Literal 是 Value Policy 最后一层，只支持兼容字符串的目标，不参与 BO Goal。
- 预期验证结果：Literal 不会抢占真实资源，也不会出现在 BO Access Policy。

## Phase #3: 文档与回归

### Task #3: 同步策略边界

**状态：** Finished

**文件：**
- 修改：`docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`
- 验证：完整 pytest
- 功能：文档明确两套策略、策略分配方和禁止路线。
- 预期验证结果：专项及完整回归通过。
