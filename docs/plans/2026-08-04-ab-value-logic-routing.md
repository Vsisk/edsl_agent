# AB 与 Parent List 取值逻辑实现计划

> **目标：** 在现有 ValueLogicGenerator 链路中实现节点逻辑白名单、SQL/table field 优先级回退、AB `list<xxx>` 返回类型和 `$record$` 字段上下文，同时保持 summary 现有语义。

**相关规格：** `docs/specs/ab-value-logic-spec.md`

**相关设计：** `docs/design-docs/ABValueLogicRouting_20260804.md`

**范围：** 修改 value logic 请求/结果契约、增加目标分类与路由边界、补充 AB item type 上下文、实现 table field 与 SQL 选择约束和测试；不重写已有 expression planner、AST 或 summary 聚合实现。

## Stage #1: 契约与目标分类

### Task #1: 增加请求和结果契约测试

**Status:** Designed

**Files:**

- Modify: `tests/test_value_logic_generator.py`
- Modify: `tests/test_edsl_gen_entry.py`
- Verify: `agent/models.py`

**功能：** 覆盖 simple leaf、AB/parent、AB field、summary field 的目标分类输入，以及业务逻辑类型和返回类型约束。

**实现说明：** 先写最小失败测试，锁定 `field_id`、`tree_node_type`、summary 特定 field 和 `list<xxx>` 的行为，不改变现有 summary 成功结果。

**预期验证结果：** 新测试在实现前因缺少分类/契约能力失败；既有 summary 测试保持可运行。

### Task #2: 实现目标分类与允许逻辑判定

**Status:** Designed

**Files:**

- Create: `agent/value_logic_routing.py`
- Modify: `agent/value_logic_generator.py`
- Modify: `agent/models.py`
- Verify: `tests/test_value_logic_generator.py`

**功能：** 代码固定 simple leaf 仅 expression，field 允许 table field/expression，AB/parent 允许 SQL/expression，其他节点允许 SQL/expression；summary 作为 field 子分支。

**实现说明：** 使用一个职责单一的分类/路由模块，避免继续向 ValueLogicGenerator 堆叠分支方法；summary 特定 field 判定复用现有字段事实和 `_is_summary_field` 语义。

**预期验证结果：** 白名单、身份优先级和非法组合均有确定结果，不依赖 LLM 自行选择。

## Stage #2: 优先级回退与 AB 上下文

### Task #3: 实现 AB SQL 优先和表达式回退

**Status:** Designed

**Files:**

- Modify: `agent/value_logic_generator.py`
- Modify: `agent/spec_orchestration/orchestrator.py`（仅在现有 BO/naming SQL 入口确需适配时）
- Modify: `tests/test_value_logic_generator.py`
- Verify: `tests/test_spec_orchestrator.py`

**功能：** AB 容器和 parent list 先解析 BO，再选择一次可返回一组 BO 的 naming SQL；无法满足时回退 expression。

**实现说明：** 复用现有 SpecOrchestrator/ResolutionCompiler 和 naming SQL 选择能力，不复制资源搜索；在提交结果前检查 `list<xxx>`。

**预期验证结果：** SQL 成功时不进入 expression planner；BO/SQL 不可用或查询不满足时只回退一次表达式路径。

### Task #4: 实现 AB `list<xxx>` item type 与 `$record$` 上下文

**Status:** Designed

**Files:**

- Modify: `agent/expression_generation/typed_context.py`
- Modify: `agent/value_logic_generator.py`
- Modify: `tests/test_typed_expression_context.py`
- Modify: `tests/test_value_logic_generator.py`

**功能：** 将 AB 容器确定的 BO/logic property item type 传递给 AB 内部 field；只暴露真实 `bo_fields` 和允许的 `$record$` 引用。

**实现说明：** 通过现有 typed context 入口增加受限投影，不创建全局虚构字段；AB field 在容器类型未确定时拒绝 table field 和 `$record$`。

**预期验证结果：** `list<BO>`、`list<logic property>` 均可提供对应字段上下文；不存在字段被拒绝。

## Stage #3: Field 映射与回归

### Task #5: 实现 table field 优先和表达式回退

**Status:** Designed

**Files:**

- Modify: `agent/value_logic_generator.py`
- Modify: `agent/models.py`
- Modify: `tests/test_value_logic_generator.py`

**功能：** AB 内部普通字段优先单字段 table field；单字段无法表达计算/组合/条件需求时回退 expression；summary 继续走现有 summary 子分支。

**实现说明：** 保留现有 BO 同名映射兼容行为，新增显式 field 身份和 item type 校验；不把 summary 误转为 table field。

**预期验证结果：** 直接字段映射路径短且可追踪，复杂 field 进入 expression，summary 回归不变。

### Task #6: 完成定向与全量验证

**Status:** Designed

**Files:**

- Verify: `tests/test_value_logic_generator.py`
- Verify: `tests/test_typed_expression_context.py`
- Verify: `tests/test_spec_orchestrator.py`
- Verify: 全量 `pytest`

**功能：** 验证白名单、优先级、回退、list 类型、`$record$`、summary 和现有普通路径。

**预期验证结果：** 定向测试通过；全量回归无新增失败；确认新增 Python 文件均小于 1000 行。
