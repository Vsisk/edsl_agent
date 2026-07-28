# 精简 NamingSQL Selector 实现计划

> **给 Codex：** 使用 `$test-driven-development` 按 RED-GREEN-REFACTOR 执行，并在结束前使用 `$verification-before-completion`。

**目标：** 将 NamingSQL 选择收敛为 profile 加载与候选选择两部分，并纳入 filter environment 流程。

**相关设计文档：** 用户当前需求（2026-07-28）

**架构：** `namingsql_profile_loader` 从 BO 注册表生成只含 BO 名、NamingSQL 名、WHERE 条件、返回字段、性能优化标记的 profile。`namingsql_seletor` 根据查询先做字段、条件和性能规则初筛，再允许 LLM 从规范候选中排序/选择；环境过滤负责调用它并保存候选结果，不再由生成器维护独立 NamingSQL 上下文与参数绑定流程。

**技术栈：** Python、Pydantic、pytest、现有 LLMClient/prompt_manager

**范围 / 非范围：** 删除旧 selector 的 context adapter、retrieval、plan validator 与绑定约束；保留表达式规划器消费候选 NamingSQL 的能力；不实现参数绑定。

---

## Phase #1: 建立最小领域行为

### Task #1: Profile loader

**状态：** Finished

**文件：**
- 创建：`agent/naming_sql_selector/namingsql_profile_loader.py`
- 创建/修改：`tests/test_namingsql_profile_loader.py`
- 功能：从 SQL 与 BO 主键元数据提取五项 profile 信息。
- 实现说明：解析 SELECT 字段和 WHERE 条件；主键等值过滤标记为性能优化。
- 预期验证结果：字段、条件、性能标记及无 WHERE 场景测试通过。

### Task #2: 两阶段 selector

**状态：** Finished

**文件：**
- 创建：`agent/naming_sql_selector/namingsql_seletor.py`
- 创建/修改：`tests/test_namingsql_seletor.py`
- 功能：按返回字段、WHERE 条件、性能优先级初筛，LLM 只能返回候选中的名称，最终返回有序候选组。
- 实现说明：无可用 LLM 时使用确定性排序；不处理参数绑定。
- 预期验证结果：字段覆盖、条件匹配、性能优先、LLM 规范化与降级测试通过。

## Phase #2: 合入 filter environment 并删除旧管线

### Task #3: 环境过滤集成

**状态：** Finished

**文件：**
- 修改：`agent/environment/environment.py`
- 修改：`agent/value_logic_generator.py`
- 修改：`agent/planner/llm_planner.py`
- 修改：相关测试
- 功能：NamingSQL 选择在 filter environment 构建期间完成并写入过滤结果。
- 实现说明：生成器只消费环境结果；移除 selector factory、context pack adapter、候选 retrieval 和 plan binding validator。
- 预期验证结果：NamingSQL 路由与普通资源过滤回归测试通过。

### Task #4: 删除遗留实现并验证

**状态：** Finished

**文件：**
- 删除：旧 NamingSQL selector 辅助模块与仅服务于旧管线的测试
- 修改：`agent/naming_sql_selector/__init__.py`
- 功能：对外只保留 profile loader 与 selector 的最小接口。
- 实现说明：清理旧 selector、绑定和 plan validator 依赖；不触碰无关资源过滤逻辑。
- 预期验证结果：定向测试与完整测试集通过，包内无旧 selector 模块依赖。
