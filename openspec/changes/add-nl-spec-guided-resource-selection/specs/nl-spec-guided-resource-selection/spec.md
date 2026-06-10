## ADDED Requirements

### Requirement: 生成自然语言规格
系统 SHALL 在资源筛选前尝试基于 `region_type + cbs_name + query + node + site_id + project_id` 生成 NL Spec。`region_type` MUST 用于获取对应区域经验库，`cbs_name` MUST 用于获取对应 CBS 术语，`query` 和 `node` MUST 作为补充上下文参与规格生成。

#### Scenario: 基于术语和区域经验生成可用规格
- **WHEN** 请求包含有效的 `region_type`、`cbs_name`、`query`、`node`、`site_id` 和 `project_id`，且术语库和区域经验库能提供匹配知识
- **THEN** 系统生成包含概念信息、取值来源候选和证据列表的 NL Spec

#### Scenario: 缺少第一版必需知识输入
- **WHEN** 请求缺少 `region_type` 或 `cbs_name`
- **THEN** 系统不生成 spec 主路径结果，并进入当前 query 驱动资源筛选 fallback

### Requirement: NL Spec 输出格式
系统生成的 NL Spec MUST 是可校验的 JSON 对象，至少包含 `concept_id`、`concept_name`、`semantic_type`、`region_type`、`value_source_candidates`、`evidence`、`needs_business_knowledge` 字段。`value_source_candidates` 中每一项 MUST 包含 `source_type` 和 `nl`，其中 `nl` 是第一版承载业务取值经验的主要字段。

#### Scenario: 输出账户余额规格
- **WHEN** `region_type` 为 `basic_info` 且 `cbs_name` 识别为账户余额
- **THEN** 系统可以生成类似包含 `concept_id: cbs.account.balance`、`concept_name: 账户余额`、`semantic_type: amount`、`region_type: basic_info`、多个 `value_source_candidates` 和 evidence 的 NL Spec

#### Scenario: 规格结构不可用
- **WHEN** 生成结果不是 JSON、缺少必要字段、`value_source_candidates` 为空或候选缺少 `source_type` 与 `nl`
- **THEN** 系统 MUST 判定该 spec 不可用，并进入当前 query 驱动资源筛选 fallback

### Requirement: 第一版范围限制
系统第一版 MUST 使用自然语言规格承载业务取值经验，不得要求本体推理、复杂概念识别或强结构化 BO 参数规划才能完成主流程。BO 查询条件、返回字段、上下文优先级和 naming SQL 使用建议 MUST 优先表达在 `value_source_candidates[].nl` 中。

#### Scenario: BO 查询经验以自然语言表达
- **WHEN** 区域经验说明账户余额可从账户余额相关 BO 查询，查询条件通常包括账户 ID、账期 ID，返回余额字段
- **THEN** 系统 MUST 将该经验保留在 `source_type=bo_field` 的 `nl` 中，而不是强制产出结构化 BO 参数计划

### Requirement: SpecResourceSelector 包装现有筛选机制
系统 SHALL 通过 `SpecResourceSelector` 或等价入口包装现有资源筛选机制。明确资源名称匹配、语义匹配和候选合并 MUST 保留，但当 NL Spec 可用时，它们的搜索空间、资源类型和检索条件 MUST 由 spec 约束。

#### Scenario: spec 主路径使用现有匹配能力
- **WHEN** NL Spec 可用，且 `value_source_candidates` 中包含 `source_type=context` 和对应 `nl`
- **THEN** 系统仍可执行现有明确资源名称匹配、语义匹配和候选合并，但候选资源 MUST 限定在 context 类型资源中，并以该候选的 `nl` 参与检索

#### Scenario: query 不再主导主路径筛选
- **WHEN** NL Spec 可用且能筛出有效资源
- **THEN** 当前 query 驱动的资源筛选逻辑 MUST NOT 作为主路径覆盖 spec 筛选结果

### Requirement: source_type 约束资源类型
系统 MUST 使用 `value_source_candidates[].source_type` 约束允许检索的资源类型，并使用同一候选的 `nl` 作为检索条件和约束来源。`context` MUST 约束到 global/local context；`bo_field` 和 `naming_sql` MUST 约束到 BO 及其字段或 naming SQL；`function` MUST 约束到 function。

#### Scenario: context 候选只筛上下文
- **WHEN** spec 候选为 `source_type=context`
- **THEN** 系统 MUST 只在 global context 和 local context 搜索空间中筛选资源

#### Scenario: BO 候选不筛函数
- **WHEN** spec 候选为 `source_type=bo_field` 或 `source_type=naming_sql`
- **THEN** 系统 MUST 只在 BO 资源及其字段、naming SQL 信息中筛选资源，不得因原始 query 的模糊词额外筛选 function

#### Scenario: 未知来源类型不可主导资源筛选
- **WHEN** spec 候选包含未知 `source_type`
- **THEN** 系统 MUST 忽略该候选或判定 spec 不可用，并记录可诊断原因

### Requirement: spec 主路径优先级
只要能够基于 `region_type + cbs_name` 生成可用规格，并且规格约束筛选能产出有效资源，后续资源筛选 MUST 以该规格为主导。planner MUST 只能使用规格筛选出的资源。

#### Scenario: spec 可用且筛出有效资源
- **WHEN** NL Spec 可用，并且 `SpecResourceSelector` 根据 spec 筛出了至少一个有效资源
- **THEN** 系统 MUST 将这些资源作为 planner 的唯一可用资源集合

#### Scenario: 原始 query 提到额外资源
- **WHEN** NL Spec 可用且筛出有效资源，但原始 query 中还出现了 spec 允许类型之外的额外资源名称
- **THEN** 系统 MUST 不把该额外资源加入 planner 可用资源集合，除非它也被 spec 约束筛选命中

### Requirement: fallback 到当前资源筛选机制
系统 MUST 在规格缺失、规格不可用或规格无法筛出有效资源时，回退到当前 query 驱动的资源筛选机制。fallback MUST 保留现有难度路由、明确资源名称匹配、语义匹配和候选合并行为。

#### Scenario: 无法生成 spec 时 fallback
- **WHEN** 术语库或区域经验库无法为 `region_type + cbs_name` 生成可用 spec
- **THEN** 系统 MUST 使用当前 query 驱动资源筛选逻辑继续生成资源环境

#### Scenario: spec 筛选结果为空时 fallback
- **WHEN** NL Spec 结构有效，但在 spec 约束下无法筛出任何有效资源
- **THEN** 系统 MUST 回退到当前 query 驱动资源筛选逻辑

### Requirement: planner 使用规格但不得越界
planner SHALL 接收 NL Spec 摘要作为业务语义约束，并 MUST 只使用 `SpecResourceSelector` 提供的已筛选资源。planner 和 repair planner MUST 禁止编造未出现在资源集合中的 BO、context、function 或 naming SQL。

#### Scenario: planner 依据 spec 选择取值路径
- **WHEN** planner 收到包含 context 优先、BO 次之、naming SQL 兜底的 NL Spec 摘要和已筛选资源
- **THEN** planner MUST 在已筛选资源范围内生成符合该取值经验的计划

#### Scenario: planner 不得使用未筛资源
- **WHEN** NL Spec 提到了某类业务概念，但对应资源未被 `SpecResourceSelector` 筛出
- **THEN** planner MUST NOT 在计划中引用该未筛出的 BO、context、function 或 naming SQL

### Requirement: 可观测的路径选择
系统 SHOULD 在内部记录本次资源筛选使用的是 `spec_guided` 还是 `query_fallback`，并在 fallback 时记录原因。该状态 MUST 至少可被单元测试或调试对象断言。

#### Scenario: 记录 spec 主路径
- **WHEN** 系统使用 NL Spec 成功完成资源筛选
- **THEN** 内部状态包含 `spec_guided` 路径标记和所使用 spec 的概念信息

#### Scenario: 记录 fallback 原因
- **WHEN** 系统因 spec 缺失、不可用或空筛选结果进入 fallback
- **THEN** 内部状态包含 `query_fallback` 路径标记和对应失败原因
