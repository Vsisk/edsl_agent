# AB 与 Parent List 取值逻辑规格

## 1. 文档状态

- 规格类型：Value Logic 行为规格
- 适用入口：`ValueLogicGenerator`
- 适用对象：AB 容器、parent list、AB 内部字段及普通节点
- 当前状态：Draft
- 本规格不包含代码实现计划

## 2. 目标

本规格定义不同 node 类型的取值逻辑白名单、逻辑选择优先级、失败回退策略、AB 返回类型以及 AB 内部字段的二次映射规则。

## 3. 核心术语

| 术语 | 定义 |
|---|---|
| `simple leaf` | `tree_node_type == simple_leaf` 的叶子节点 |
| AB 容器 | `ab_pivot_table` 或 `ab_two_level_table` 节点 |
| parent list | `tree_node_type == parent_list` 的列表容器 |
| AB 内部字段 | node 存在非空 `field_id` 的字段节点；summary 是其中一种受限字段类型 |
| summary 字段 | AB 内部字段中的特定 field，只有满足字段类型/配置约束时才允许 summary |
| `xxx` | 一个 AB 集合中的元素类型，可以是 BO 或 logic property |
| `$record$` | 当前 AB 容器返回的 `xxx` 元素的字段上下文 |

## 4. 逻辑类型白名单

### 4.1 规则

| 节点条件 | 允许的取值逻辑 |
|---|---|
| `tree_node_type == simple_leaf` | 仅 `edsl_expression` |
| `node_id` 非空，且类型为 `ab_pivot_table`、`ab_two_level_table` 或 `parent_list` | `sql`、`edsl_expression` |
| `field_id` 非空 | `table_field`、`edsl_expression` |
| 其他节点 | `sql`、`edsl_expression` |

`table_field` 只有在 node 存在 `field_id` 时允许。普通节点、AB 容器和 parent list 不得生成 `table_field`。

`summary` 不作为独立的目标分类，而作为 AB 内部字段分支中的一种字段类型：

- 只有特定 field（由现有 field 类型、summary 配置或字段 schema 判定）允许使用 summary。
- 非特定 field 请求 summary 时返回 `UNSUPPORTED_SUMMARY_FIELD`，不得自动把它当作普通表达式或任意 summary。
- 已有 summary 的聚合逻辑、`summary_type` 和明细字段关联规则保持不变。
- summary 字段仍属于 `field_id` 分支，但其逻辑选择由现有 summary 专用逻辑处理，不参与 `table_field` 优先级竞争。

### 4.2 身份判定优先级

1. `simple_leaf` 优先判定为 simple leaf，只允许表达式。
2. 非 simple leaf 中，`field_id` 非空时判定为 AB 内部字段；若该 field 是允许 summary 的特定 field，则进入现有 summary 子分支。
3. 否则，`node_id` 非空且 `tree_node_type` 属于 AB/parent 白名单时判定为 AB 容器或 parent list。
4. 其他节点进入通用节点逻辑。
5. 类型缺失、类型未知或身份字段冲突时返回结构化错误，不交由 LLM 猜测。

## 5. 逻辑选择优先级

多种逻辑均可用时，优先级由本地代码固定：

| 目标 | 首选 | 回退条件 | 回退逻辑 |
|---|---|---|---|
| AB 容器 / parent list | `sql` | BO 未确定、无匹配 naming SQL、一次查询无法满足条件、结果不是 list | `edsl_expression` |
| AB 内部字段 | `table_field` | 单个字段无法表达需求、字段不存在、需要计算/组合/条件逻辑 | `edsl_expression` |
| 允许 summary 的特定 field | 现有 summary 逻辑 | 不满足 summary 字段条件 | 返回校验失败，不降级为任意 summary |
| 其他非 simple leaf | `sql`（存在明确 SQL 事实时） | SQL 不可用或无法满足需求 | `edsl_expression` |
| simple leaf | `edsl_expression` | 表达式生成失败 | 返回失败，不得切换 SQL/table field |

LLM 只能在当前路由允许的逻辑类型内生成内容，不得改变优先级。

### 5.1 `target` 到生成分支的派发

目标分类结果必须显式产出 `primary_branch` 和 `fallback_branch`，后续生成入口按分支派发，而不是继续依赖 `is_ab` 或父节点 SQL 条件隐式穿透：

| target kind | primary branch | fallback branch |
|---|---|---|
| `simple_leaf` | `expression` | 无 |
| `ab_container` / `parent_list` | `sql` | `expression` |
| `ab_field` 普通字段 | `table_field` | `expression` |
| `ab_field` summary 字段 | `summary` | 无通用回退 |
| `generic` | `sql` | `expression` |

生成入口必须保持四条清晰分支：

- `sql` branch：先调用一次 LLM 在所有可用 BO 中判断是否能选择目标 BO；选不到 BO 时直接回退 expression。选中 BO 后，只读取该 BO 的 `naming_sql_list` 并调用 NamingSQL selector 选择 NamingSQL；再进入参数绑定，参数优先从 context-only 资源筛选结果中的 global context、local context 或用户显式常量中选择。BO、function、未筛出的 context 和虚构常量都不能作为参数来源。单个参数绑定失败时不回退 expression，而是由本地代码填充默认常量空字符串 `""`，然后返回 `sql` 结果。
- `expression` branch：复用现有 planner、AST、类型校验链路。
- `table_field` branch：仅当 node 存在 `field_id` 时可进入；单字段映射不可用或不能满足需求时回退 expression。
- `summary` branch：作为 field 的受限子分支，复用现有 summary 逻辑，不进入普通 table field 优先级竞争。

## 6. AB 容器 SQL 链路

AB 容器和 parent list 优先使用 SQL：

```text
识别目标 AB/parent
  -> 确认目标 BO
  -> BO 未选时先从 registry/当前数据源选择 BO
  -> 选择一次可查询出一组符合条件 BO 的 naming SQL
  -> 对 NamingSQL 参数做 context-only 资源筛选和参数绑定
  -> 绑定查询条件
  -> 校验结果为 list<xxx>
  -> 成功则返回 sql
  -> 失败则回退 edsl_expression
```

约束：

- BO 名称必须来自真实 registry 或 AB 数据源，不能由 LLM 虚构。
- 未确定目标 BO 前不得搜索或选择 NamingSQL。
- NamingSQL 选择必须限定在目标 BO 自己的 `naming_sql_list`，不得跨 BO 混选。
- 一次 naming SQL 必须能够查询出一组符合条件的 BO。
- `select_one` 或 scalar 结果不能直接满足 AB/parent list 规则。
- SQL 无法完整表达用户需求时，回退表达式，而不是拼接多个不满足契约的查询。
- 回退表达式时必须保留已解析的 BO、字段和目标类型上下文。

## 7. AB 返回类型与内部字段映射

### 7.1 AB 返回类型

一个 AB 的返回类型固定为：

```text
AB = list<xxx>
xxx = BO | logic property
```

AB SQL 或表达式成功后必须确定 `xxx`，并产出可供下游使用的 item type 描述：

- BO 名称或 logic property 标识
- item 的基础类型
- 可用 `bo_fields`
- 字段类型和 table field 信息
- 可供 `$record$` 引用的字段集合

### 7.2 AB 内部字段

AB 内部字段是对 AB 返回的 `list<xxx>` 中每个元素进行二次映射，不是重新发起一次独立 BO 查询：

```text
AB: list<xxx>
  -> AB internal field
  -> map(each xxx, target field)
```

因此：

- `table_field` 只能从 AB 容器确定的 `xxx` item type 中选择。
- `$record$` 只能引用该 item type 的真实字段，例如 `$record$.amount`。
- `xxx` 是 BO 时，字段来源为该 BO 的 `bo_fields`。
- `xxx` 是 logic property 时，字段来源为该 logic property 的属性定义。
- `xxx` 尚未确定时，禁止生成 `table_field` 或 `$record$` 引用。
- AB 内部字段可以返回 scalar，不继承 AB 容器的 list 返回约束。

## 8. 表达式生成规则

### 8.1 simple leaf

- 只能进入 `edsl_expression` 生成链路。
- 表达式应经过现有 Planner、AST 构建和类型校验。
- 生成失败返回结构化失败，不回退到 SQL 或 table field。

### 8.2 AB/parent 表达式回退

- 只有 SQL 首选路径无法满足需求时进入。
- 表达式结果必须为 list。
- 表达式必须表达 `list<xxx>`，不能只返回一个 BO 字段。

### 8.3 AB 内部字段表达式回退

- 只有单个 `table_field` 无法表达需求时进入。
- 允许使用 `$record$` 及其已验证字段。
- 表达式可以做计算、组合、条件判断或字段转换。
- 结果类型按目标字段声明校验，可以是 scalar。

### 8.4 AB 内部 summary 字段

- summary 属于 AB 内部 field 分支。
- 仅特定 field 可以进入 summary 子分支；判定依据使用现有字段类型、summary 配置和 schema 约束。
- 现有 summary 逻辑继续负责聚合类型、明细字段和结果构造。
- summary 不走 `table_field` 优先级，也不因普通 field 的 table field 回退规则而改变语义。

## 9. 返回结果契约

业务逻辑类型建议使用：

```text
edsl_expression | sql | table_field
```

如果当前 `ValueLogicResult.logic_type` 仍兼容已有的 `expression`、`bo_field_mapping` 等值，则必须新增独立的业务逻辑类型字段，不能只通过 `source_type` 推断。

结果至少应包含：

- node 标识
- 业务逻辑类型
- 逻辑内容或引用
- `is_list`
- 目标数据类型
- AB 容器场景下的 `ab_item_type`
- 来源信息
- 结构化校验错误

## 10. 错误码

| 错误码 | 含义 |
|---|---|
| `INVALID_VALUE_LOGIC_TARGET` | node 身份缺失、未知或冲突 |
| `UNSUPPORTED_VALUE_LOGIC_TYPE` | 当前节点不允许该逻辑类型 |
| `AB_BO_NOT_RESOLVED` | AB 容器无法确定目标 BO |
| `NAMING_SQL_NOT_FOUND` | 没有可用 naming SQL |
| `SQL_QUERY_CANNOT_SATISFY_REQUEST` | 一次 SQL 无法完整满足需求 |
| `AB_RETURN_TYPE_MUST_BE_LIST` | AB/parent 返回类型不是 list |
| `AB_ITEM_TYPE_NOT_RESOLVED` | 无法确定 `xxx` |
| `TABLE_FIELD_NOT_FOUND` | 找不到目标 table field |
| `TABLE_FIELD_CANNOT_SATISFY_REQUEST` | 单个 table field 无法表达需求 |
| `RECORD_FIELD_NOT_FOUND` | `$record$` 字段不在允许上下文中 |
| `UNSUPPORTED_SUMMARY_FIELD` | 当前 field 不允许使用 summary |
| `VALUE_LOGIC_VALIDATION_FAILED` | 最终表达式、SQL 或字段映射校验失败 |

## 11. 验收标准

### 11.1 白名单

1. simple leaf 请求 SQL 时被拒绝。
2. simple leaf 请求 table field 时被拒绝。
3. AB/parent 请求 SQL 或表达式时通过路由校验。
4. AB/parent 请求 table field 时被拒绝。
5. 有 `field_id` 的节点请求 table field 时通过路由校验。
6. 无 `field_id` 的节点请求 table field 时被拒绝。
7. 允许 summary 的特定 field 进入现有 summary 子分支。
8. 非特定 field 请求 summary 时被拒绝。

### 11.2 优先级与回退

1. AB/parent 同时可用 SQL 和表达式时选择 SQL。
2. BO 未选时先选择 BO，再选择 naming SQL。
3. 一次 naming SQL 无法满足需求时回退表达式。
4. AB 内部字段同时可用 table field 和表达式时选择 table field。
5. 单个 table field 无法表达需求时回退表达式。
6. simple leaf 表达式失败时不切换到其他逻辑。

### 11.3 类型与上下文

1. AB SQL 返回 `list<BO>` 时通过，并暴露对应 `bo_fields`。
2. AB 表达式返回 `list<logic property>` 时通过，并暴露对应属性上下文。
3. AB/parent 返回 scalar 时失败。
4. AB 内部字段可以基于 `xxx` 生成 table field 映射。
5. `$record$.field` 仅在字段存在于当前 `xxx` item type 时通过。
6. 不存在的 `$record$` 字段被拒绝。
7. AB 内部字段返回 scalar 时不因容器 list 规则失败。

### 11.4 兼容性

1. 普通非 AB 节点保留现有表达式和 SQL 兼容行为。
2. 现有 summary 逻辑整合在 AB 内部 field 分支中，且仅对特定 field 生效。
3. 现有 SpecOrchestrator、ContextPack、TypedContext、AST 和 value logic 回归测试通过。
4. 所有失败结果不包含可执行的半成品逻辑。

## 12. 完成定义

本规格实现完成需满足：

1. 所有节点均按本规格得到唯一目标分类。
2. 逻辑白名单和优先级由本地代码强制执行。
3. AB/parent 的 SQL 首选与表达式回退可验证。
4. AB 内部字段的 table field 首选与表达式回退可验证。
5. `list<xxx>` 和 `xxx` 到内部字段的映射链路可验证。
6. `$record$` 只暴露当前 AB item type 的真实字段。
7. 全部验收用例和既有回归测试通过。
