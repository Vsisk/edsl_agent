# ABValueLogicRouting_20260804

## 核心功能（WHAT）

### 需求背景（WHY）

费用表、详单表等 AB 内部表以及 parent list 的字段，取值逻辑并不适合沿用普通叶子节点的统一表达式生成路径。当前系统已经能识别部分 AB/summary/SQL 字段映射场景，但路由条件主要分散在 `is_ab`、父节点数据源和字段名匹配中，无法完整表达以下业务规则：

1. 输入 node 有 `node_id`，且 `tree_node_type` 为 `ab_pivot_table`、`ab_two_level_table` 或 `parent_list` 时，允许的取值逻辑为 `edsl_expression` 和 `sql`。
2. 输入 node 有 `field_id` 时，表示 AB 内部字段，允许的取值逻辑为 `edsl_expression` 和 `table_field`。
3. parent list 和 AB 表的取值逻辑返回类型必须为 list。
4. AB 内部字段的表达式可以使用 `$record$` 字段，表示当前 AB 检索得到的 BO 表中的其他字段（`bo_fields`）。

本设计先统一整个链路的识别、路由、上下文、校验和输出契约，暂不进入代码实现。

### 需求目标（GOAL）

- 根据 node 身份和 `tree_node_type` 稳定识别三类目标：普通 AB/parent 容器、AB 内部字段、非本需求节点。
- 在生成前约束可选逻辑类型，禁止 LLM 输出不适用的逻辑类型。
- 为 AB 内部字段提供带 `$record$` 命名空间的 BO 字段上下文。
- 在路由层和最终校验层共同保证 parent list/AB 表结果为 list。
- 保留现有普通表达式、summary 和 BO 字段映射能力，避免改变非本需求节点的行为。
- 让上游业务术语（`edsl_expression`、`sql`、`table_field`）与当前内部输出模型建立明确映射。

## 范围边界

### 纳入范围

- `ValueLogicRequest.node` 的身份识别和优先级。
- AB 表、parent list、AB 内部字段的逻辑类型白名单。
- 当前 BO、`bo_fields`、AB 数据源和父级上下文的组装。
- list 返回类型约束及表达式/SQL/table field 的结果校验。
- 失败结果、兼容输出和测试场景设计。

### 不纳入范围

- 不实现本轮代码改动。
- 不重新设计 SQL/naming SQL 资源定义、SQL 执行器或 BO 注册表。
- 不改变普通非 AB 节点的表达式生成语法、AST 和资源检索策略。
- 不定义 `$record$` 的运行时数据填充机制；本设计只定义生成时可见的字段上下文和引用契约。
- 不扩展 summary 字段的聚合语义。

## 当前架构与问题定位

当前主链路为：

```text
ValueLogicRequest
  -> ValueLogicGenerator.generate()
  -> ResourceLoader.load_resource()
  -> ContextPackManager.build()
  -> 非 AB：普通表达式规划
  -> AB：summary / 父节点 SQL 的 BO 字段映射 / 普通表达式规划
  -> TypedExpressionContextBuilder
  -> Planner
  -> AST 构建与校验
  -> EDSL expression
  -> ValueLogicResult
```

关键现状：

- `agent/models.py` 的 `ValueLogicRequest` 只保存原始 node 和 `is_ab`，没有显式的目标逻辑类型字段。
- `ValueLogicGenerator._generate_field_logic()` 先判断 summary，再进入普通字段逻辑。
- `_generate_normal_field_logic()` 当前对父节点 SQL 尝试 BO 字段同名映射，否则回退到表达式规划。
- `models.py` 已有数据源分支模型，包含 SQL、expression 和 table field 概念，但它与 `agent.models.ValueLogicResult.logic_type` 的命名并不一致。
- 当前 `$record$` 未在已确认的 typed context 契约中作为 AB 内部字段专用命名空间出现，需要新增显式投影，不能让 Planner 自行猜测。

因此，本需求应增加一个位于资源加载之后、表达式规划之前的“目标分类与逻辑路由层”，并在输出前增加统一契约校验。

## 目标分类与优先级

### 分类规则

分类必须基于 node 本身，不以 `is_ab` 单字段作为唯一依据：

| 分类 | 必要条件 | 语义 | 允许逻辑 |
| --- | --- | --- | --- |
| AB/parent 目标 | 有 `node_id`，且 `tree_node_type` 是 `ab_pivot_table`、`ab_two_level_table` 或 `parent_list` | 费用表、详单表或 parent list 的目标取值 | `edsl_expression`、`sql` |
| AB 内部字段 | 有 `field_id` | AB 检索得到的 BO 记录中的字段 | `edsl_expression`、`table_field` |
| 其他节点 | 不满足以上条件 | 沿用现有普通/summary 分支 | 现有兼容逻辑 |

### 判定优先级

1. 先校验 node 结构是否为对象。
2. 若 `field_id` 存在且非空，优先判定为 AB 内部字段；即使同时存在 `node_id`，也不能误路由为 AB 表容器。
3. 否则若 `node_id` 存在且 `tree_node_type` 属于 AB/parent 白名单，判定为 AB/parent 目标。
4. 其他情况进入兼容分支；兼容分支仍可依据现有 `is_ab`、summary 和父节点 SQL 逻辑工作，但不能宣称满足本需求的强约束。
5. `tree_node_type` 缺失、未知或 ID 同时出现但语义冲突时，应返回结构化校验失败，不交给 LLM 猜测。

建议内部建立不可变的 `ValueLogicTargetKind`：`ab_container`、`ab_field`、`legacy`，并同时产出 `allowed_logic_types`、`required_is_list`、`record_fields` 和数据源上下文。

## 实现流程（HOW）

### 1. 请求归一化

在 `ValueLogicGenerator.generate()` 资源加载后，对 node 做一次归一化：

- 读取 `node_id`、`field_id`、`tree_node_type`，统一空字符串和缺失值处理。
- 读取用户明确指定的逻辑类型（如请求协议已有该字段）；若当前请求协议没有该字段，应在设计落地时补充或从结构化 spec 中明确提取，不能从自然语言模糊推断为强约束。
- 解析 `is_list`/返回类型期望；AB/parent 目标最终强制覆盖为 list 约束。
- 生成目标分类对象，供后续上下文、Planner 和校验层复用。

### 2. 资源和上下文准备

资源加载仍复用现有 `ResourceLoader`。新增的上下文投影如下：

```text
target_kind
allowed_logic_types
required_return_type: list | unconstrained
current_node
parent_node
ab_data_source
bo_name
bo_fields
record_fields: $record$.<field_name>
```

其中：

- `bo_name` 优先来自 AB 节点/父节点实际 SQL 数据源的 `sql_query.bo_name`，无法解析时不得伪造。
- `bo_fields` 来自已加载 BO registry 的 `property_list`，只暴露字段名、基础数据类型、可用别名等生成所需事实。
- 对 `ab_field`，将每个 BO 字段投影为 `$record$.field_name`；字段名必须来自真实 registry，禁止仅依据用户描述创建虚构字段。
- 对 `ab_container`，上下文重点是 AB/parent 的数据源和外部资源，不自动开放 `$record$`，除非该节点本身明确处于 BO 记录上下文中。
- 当前 ContextPack、TypedExpressionContext 和 Planner prompt 应消费同一个目标分类结果，避免出现“路由允许但 prompt 不知道”或“prompt 暴露了不允许类型”的分裂。

### 3. 逻辑类型路由

路由层先执行白名单校验，再选择生成器：

```text
ab_container
  ├─ edsl_expression -> expression planner / AST / expression validation
  └─ sql              -> SQL/naming SQL 选择与 SQL 结果校验

ab_field
  ├─ edsl_expression -> expression planner，允许 $record$.field
  └─ table_field      -> 直接字段映射与字段存在性校验

legacy
  └─ 现有兼容链路
```

逻辑类型与当前 `ValueLogicResult` 的兼容映射建议如下：

| 业务逻辑类型 | 当前内部结果建议 | 说明 |
| --- | --- | --- |
| `edsl_expression` | `logic_type="expression"` | `expression` 保存渲染后的 EDSL expression |
| `sql` | 新增明确的 SQL 结果分支，或在协议层增加 `logic_type="sql"` | 不应伪装成普通 expression；需要携带 SQL/naming SQL 引用及返回类型 |
| `table_field` | 复用/演进 `bo_field_mapping` | `expression` 可保存字段名，source 标记为 table field；建议最终显式区分 |

这里存在一个必须在实现前确认的协议决策：如果上游要求返回值中的 `logic_type` 必须严格使用 `edsl_expression`、`sql`、`table_field`，则应升级 `ValueLogicResult` 的枚举；如果外部协议暂时兼容现有值，则需要增加独立的 `value_logic_type` 字段，不能只靠 `source_type` 猜测。

### 4. 各分支约束

#### AB/parent 的 `edsl_expression`

- 进入现有 Planner/AST 生成链路。
- 目标返回类型必须是 list；AST 校验结果不是 list 时失败。
- 上下文应明确当前目标是 AB/parent，防止生成单值 BO 字段映射。

#### AB/parent 的 `sql`

- 只允许使用已解析的 AB/parent 数据源、SQL 或 naming SQL 资源。
- SQL 结果必须声明为 list；`select_one` 或单对象结果不能满足本规则，除非上游另行定义包装语义。
- SQL 参数的取值依赖仍走现有 Context/BO 字段递归链路，但最终返回契约由本层校验。
- SQL 内容、命名 SQL ID、BO 名称等敏感/执行细节按现有 ContextPack 脱敏策略处理。

#### AB 内部字段的 `edsl_expression`

- 允许引用 `$record$.<bo_field>`。
- `$record$` 只允许引用当前 AB 检索 BO 的真实 `bo_fields`。
- 表达式结果类型按目标字段的声明类型校验；该字段本身不是 list 时不应被强制转换为 list，list 强约束只适用于 AB/parent 容器目标。
- 如果用户请求引用不存在的 `$record$` 字段，应结构化失败并给出可用字段集合或字段名提示。

#### AB 内部字段的 `table_field`

- 直接读取目标字段与 BO table field 的映射。
- 映射前校验 field id、字段名、BO 名称和 registry 中的字段事实。
- 不经过普通表达式 Planner，避免把直接映射误生成为计算表达式。

### 5. 返回类型校验

返回类型校验必须分两层：

1. 生成前：把 `required_return_type=list` 传入 prompt、typed context、SQL 分支和 planner。
2. 生成后：统一检查结果的 `return_type.is_list`；AB/parent 目标不是 list 时返回 `validation_failed`，不得仅依赖 LLM 自报类型。

校验失败至少包含：`target_kind`、`logic_type`、`expected_is_list`、`actual_is_list`、`node_id/field_id` 和可定位的错误码。

### 6. 输出与上游兼容

建议结果增加稳定的内部元数据（最终字段名需与上游协议确认）：

- `target_kind`
- `value_logic_type`
- `is_list`
- `bo_name`
- `bo_field`
- `sql/naming_sql reference`（不直接泄露 SQL body）

现有 `source` 字段可继续保留作为兼容投影，但不再承担逻辑类型判定职责。

## 状态、触点与职责归属

| 触点 | 主要职责 | 失败归属 |
| --- | --- | --- |
| `ValueLogicRequest` 归一化 | 身份字段和逻辑类型合法性 | request validation |
| target classifier | 分类与白名单 | target classification |
| ResourceLoader/registry | BO、field、SQL 真实事实 | resource resolution |
| ContextPack/typed context | 向 Planner 暴露受限上下文 | context construction |
| Planner/SQL selector | 生成候选逻辑 | planning/selection |
| AST/SQL/table-field validator | 语法、字段存在性、返回类型 | value logic validation |
| `ValueLogicResult` | 稳定输出和错误信息 | result contract |

## i18n

本需求不新增 UI。错误码和内部逻辑类型使用稳定英文枚举；用户可见错误文案沿用现有中英文提示机制。建议新增错误码：

- `UNSUPPORTED_VALUE_LOGIC_TYPE`
- `INVALID_AB_TARGET_IDENTITY`
- `AB_RETURN_TYPE_MUST_BE_LIST`
- `RECORD_FIELD_NOT_FOUND`
- `SQL_RESULT_TYPE_MUST_BE_LIST`

## 测试用例

### 分类与白名单

- `node_id + ab_pivot_table` 只允许 `edsl_expression/sql`。
- `node_id + ab_two_level_table` 只允许 `edsl_expression/sql`。
- `node_id + parent_list` 只允许 `edsl_expression/sql`。
- `field_id` 只允许 `edsl_expression/table_field`。
- 同时存在 `field_id` 和 `node_id` 时优先判定 AB 内部字段。
- 未知 `tree_node_type` 或 ID 冲突返回结构化失败。

### 返回类型

- 三类 AB/parent 目标的 expression 结果为 list 时通过。
- 三类 AB/parent 目标的 expression 结果为 scalar 时失败。
- SQL 返回 list 通过，`select_one`/scalar 返回失败。
- AB 内部字段 scalar 返回不因 list 规则失败。

### `$record$`

- 真实 `bo_fields` 可被 `$record$.amount` 引用并通过类型校验。
- 不存在的 `$record$.missing` 被拒绝。
- `$record$` 不泄露到非 AB 内部字段场景。
- BO 无法解析时不生成虚构 `$record$` 字段。

### 兼容回归

- 普通非 AB 节点仍进入现有表达式链路。
- 既有 summary 逻辑不被新的 AB 容器分类误截获；实现时需明确 summary 与 `field_id` 的优先级。
- 现有父节点 SQL 同名 BO 字段映射仍保持兼容。
- 现有 SpecOrchestrator、ContextPack、TypedContext 和 AST 测试全部回归通过。

## 设计结论与实现前决策

本需求的核心不是新增一个单独的 Planner 分支，而是建立“目标身份 -> 允许逻辑 -> 上下文投影 -> 生成器 -> 强校验 -> 兼容输出”的单一链路。分类和约束必须在代码层确定，LLM 只负责在已允许的逻辑类型内生成内容。

## 需求修订：节点约束、优先级与 AB item 类型

以下规则覆盖本文前文中较宽泛的兼容描述，作为最终设计约束：

### 1. 节点类型与允许逻辑

- `tree_node_type == simple leaf` 的节点只能生成 `edsl_expression`。即使自然语言中出现 SQL 或字段映射意图，也不能切换到 SQL 或 `table_field`；表达式生成失败则返回校验失败。
- 其他节点允许 `sql` 和 `edsl_expression`。
- 只有存在 `field_id` 的节点才允许 `table_field`。因此没有 `field_id` 的普通节点、AB 容器和 parent list 都不能生成 `table_field`。
- 有 `field_id` 的节点继续按 AB 内部字段处理；`field_id` 与 `node_id` 同时存在时，字段身份优先。

### 2. 多逻辑节点的优先级与回退

优先级由代码固定，不交由 LLM 决定：

```text
AB 容器 / parent list
  -> 优先 SQL
  -> 若 BO 未选，先选择 BO
  -> 选择一次可查询出一组符合条件 BO 的 naming SQL
  -> 一次查询无法满足需求：回退 edsl_expression

AB 内部字段（field_id）
  -> 优先 table_field
  -> 单个 table field 无法表达需求：回退 edsl_expression

其他节点
  -> sql 或 edsl_expression，按是否存在可用 SQL 事实和需求判断

simple leaf
  -> 仅 edsl_expression
```

“一次查询无法满足”包括：无法确定目标 BO、没有合适 naming SQL、查询条件无法完整绑定、查询结果不能表达目标集合，或结果类型不符合要求。回退时应复用已经解析出的上下文，不重新让 LLM 猜测 BO 或字段。

### 3. AB 的 `list<xxx>` 与内部字段二次映射

一个 AB 的返回值语义固定为：

```text
AB = list<xxx>
xxx = BO | logic property
AB internal field = 对 list<xxx> 中每个 xxx 做二次映射
```

因此，AB 容器的取值逻辑成功后，必须产出可供下游使用的 `ab_item_type`。该类型描述 `xxx` 的来源及可用字段：

- 当 `xxx` 是 BO 时，包含 BO 名称、`bo_fields`、字段类型和可用 table fields。
- 当 `xxx` 是 logic property 时，包含 logic property 的名称、类型和可映射属性。
- AB 内部字段的 `table_field` 只能从这个 `ab_item_type` 中选择单个字段。
- AB 内部字段表达式的 `$record$` 也只能引用这个 `ab_item_type` 中的字段，例如 `$record$.amount`。
- AB 容器本身必须校验为 `list<xxx>`；AB 内部字段的最终结果可以是 scalar，不继承容器的 list 约束。

这意味着 AB 内部字段不是再次独立查询 BO，而是对 AB 容器已确定的集合元素进行二次映射。若容器的 `xxx` 类型未确定，内部字段不得生成 `table_field` 或 `$record$` 引用，应先解决容器类型或返回结构化失败。

### 4. Summary 与 AB 内部字段的关系

summary 是 AB 内部字段的一种受限类型，不是独立于 field 的目标分类。现有 summary 分支逻辑保持不变，但在目标分类上归入 `ab_field`：

- 只有特定 field 才能进入 summary 子分支；判定依据使用现有 field 类型、summary 配置和 schema 约束。
- summary 字段不参与普通 field 的 `table_field` 优先级竞争。
- 非特定 field 请求 summary 时返回结构化校验失败，不降级为任意 summary。
- summary 的聚合类型、明细字段关联和结果构造继续使用现有逻辑。

### 5. 对原设计路由表的最终解释

| 目标 | 首选逻辑 | 回退逻辑 | 返回类型 |
| --- | --- | --- | --- |
| simple leaf | `edsl_expression` | 无 | 按字段类型 |
| AB 容器 / parent list | `sql`（必要时先选 BO，再选 naming SQL） | `edsl_expression` | `list<xxx>` |
| AB 内部字段（有 `field_id`） | `table_field` | `edsl_expression` | 按目标字段类型 |
| AB 内部 summary 字段 | 现有 summary 逻辑 | 无通用降级；非法 field 直接失败 | 按 summary 规则 |
| 其他节点 | `sql` 或 `edsl_expression` | 另一种可用逻辑 | 按节点声明 |

该修订同时明确：SQL 是 AB 容器和 parent list 的首选能力，table field 是普通 AB 内部字段的首选能力；summary 作为特定 field 的独立子分支保持现有逻辑。SQL 或 table field 不能完整表达需求时，普通场景才进入表达式生成。

实现前需要产品/上游确认一项协议问题：最终输出是否把 `logic_type` 直接升级为 `edsl_expression/sql/table_field`，还是保留当前 `expression/bo_field_mapping` 并新增业务层逻辑类型字段。该选择会影响 `ValueLogicResult`、调用方反序列化和回归测试，但不影响本文的目标分类和链路设计。
