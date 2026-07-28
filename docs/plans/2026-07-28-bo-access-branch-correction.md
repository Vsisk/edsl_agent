# BO Access 分支修正实现计划

> **给 Codex：** 按本计划使用测试驱动开发完成实现。

**目标：** 严格实现 `BO field → NamingSQL → select/select_one → 条件 Goal 递归求解` 的 BO 取值链。

**相关设计文档：** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** 将 BO access 拆成代码固定的 NamingSQL 层和 Select fallback 层。NamingSQL 层只返回目标 BO 的 canonical NamingSQL；全部候选失败后才进入 Select 层。Select 层从 query 中识别明确条件字段，无明确条件时使用目标 BO 的全部 key 字段，并将条件值作为普通 Goal 递归求解。

**技术栈：** Python、Pydantic、pytest

**范围 / 非范围：** 修改 SpecOrchestrator 的 BO 获取状态机、资源搜索候选和结果编译；不修改当前工作区中未提交的 TypedContext/Planner 改动，不改变公开 `ValueLogicResult`。

---

## Phase #1: 固化 BO 获取分支

### Task #1: 拆分 NamingSQL 与 Select 层

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/models.py`
- 修改：`agent/spec_orchestration/search.py`
- 修改：`agent/spec_orchestration/orchestrator.py`
- 验证：`tests/test_spec_orchestrator.py`
- 验证：`tests/test_spec_orchestrator_search.py`
- 功能：NamingSQL 始终先于 Select，跨 BO relation 不再与 NamingSQL 混选。
- 实现说明：保留 `BO_ACCESS` 表示 NamingSQL 层，新增紧随其后的 `BO_SELECT` 层。
- 实现说明：BO field 创建的 BO 依赖 Goal 使用受限层级 `[BO_ACCESS, BO_SELECT]`，不得重新搜索 Context 或 BO field；其参数/条件子 Goal 仍使用完整层级。
- 预期验证结果：有可闭合 NamingSQL 时不搜索 Select；NamingSQL 无候选或全部失败时才搜索 Select。

## Phase #2: Select 条件递归求解

### Task #2: 构造 Select 候选和条件 Goal

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/search.py`
- 修改：`agent/spec_orchestration/orchestrator.py`
- 验证：`tests/test_spec_orchestrator.py`
- 功能：选择 `select`/`select_one`，并递归求解条件字段值。
- 实现说明：query 明确出现的非目标字段优先作为条件；否则使用全部 `data_type=key` 字段。条件输入使用 `FILTER_VALUE` Goal，按普通资源优先级递归。
- 预期验证结果：单主键、联合主键、显式条件字段和条件值失败回滚均有测试覆盖。

## Phase #3: 编译与回归

### Task #3: 输出 Select 编排和资源列表

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/compiler.py`
- 修改：`docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`
- 验证：`tests/test_spec_orchestrator_compiler.py`
- 功能：最终自然语言 Spec 明确 select/select_one、目标 BO、目标字段和条件绑定，筛选 BO 保留所需字段。
- 实现说明：仅编译 committed resolution，不暴露失败的 NamingSQL 候选。
- 预期验证结果：专项测试及完整 pytest 回归通过。
