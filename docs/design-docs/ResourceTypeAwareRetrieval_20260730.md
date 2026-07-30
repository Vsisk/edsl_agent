# ResourceTypeAwareRetrieval_20260730

## 核心功能（WHAT）

将 `OrchestratorResourceSearch` 当前统一的关键词包含匹配改为按资源类型分流的候选召回：

- Context 根据 canonical 名称或 path 做确定性匹配；
- BO Field 以单个 `PropertyTerm` 为索引和召回粒度，对每个关键词、别名分别计算余弦相似度，取最高分排序，并返回对应 BO 与 Property；
- Function 先按返回类型和基数做硬过滤，再用相同的独立关键词余弦评分做粗召回，最终仍由现有 LLM Coverage Decision 根据完整 query 选择。

`keywords` 和 `aliases` 参与正向召回；`negative_keywords` 仅用于确定性排除，不参与负向向量计算。

### 需求背景（WHY）

当前 `agent/spec_orchestration/search.py` 使用 `_matches()` 统一搜索 Context、BO Field 和 Function。统一的子串匹配无法稳定覆盖中文业务语义、英文缩写和字段别名，也忽略了不同资源的固有约束：

- Context 已有 canonical 名称和作用域 path，语义向量可能引入不必要的误召回；
- BO 的真正目标是某个 `property_list` 字段，而不是整个 BO；
- Function 名称相似不代表操作语义相同，且函数能否覆盖 Goal 首先受返回类型、基数和真实参数约束。

### 需求目标（GOAL）

1. Context 搜索只返回名称或 path 可确定性命中的可见 canonical 资源。
2. BO Field 对每个字段分别召回，候选包含真实 `BoRegistry` 和 `PropertyTerm`。
3. 多个关键词和别名分别生成查询向量，资源得分取所有查询向量中的最高余弦相似度。
4. Function 在向量召回前完成返回类型和基数过滤，向量结果只负责压缩几百个函数形成的候选池。
5. 所有候选继续交给现有 Coverage LLM 做最终语义判断，并由代码执行 canonical、类型和依赖校验。
6. Embedding 异常时使用有界词法召回，不向 LLM 暴露全量 Registry。

### 范围边界

纳入范围：

- `VISIBLE_VALUE`、`BO_FIELD`、`FUNCTION` 三个搜索层；
- embedding client 注入、批量向量计算、余弦排序和失败降级；
- exact match 优先、负向关键词排除、稳定排序与 Top-K 限制；
- 搜索单元测试和 Spec Orchestrator 相关回归。

不纳入范围：

- NamingSQL、BO Select 和 Literal 的现有策略；
- 修改 LLM Goal、Keyword 或 Coverage 输出契约；
- 引入外部向量数据库；
- 由余弦分数直接提交 Function；
- 持久化 Registry embedding 缓存。本轮先在搜索实例内惰性缓存资源向量，缓存键包含资源搜索文本。

## 实现流程（HOW）

### 统一入口与策略分流

`OrchestratorResourceSearch.search()` 保持现有接口和 Tier 分派。构造函数增加可选 `embedding_client`，便于生产环境复用现有 `EmbeddingClient`，测试注入确定性 fake。

```text
GoalSearchRequest
  ├─ VISIBLE_VALUE → Context deterministic matcher
  ├─ BO_FIELD      → exact/lexical + per-keyword cosine retrieval
  └─ FUNCTION      → return-type gate + exact/lexical + cosine coarse retrieval
                                      ↓
                            existing Coverage LLM
```

### Context

Context 不使用 embedding。对 `context_name` 及其 path 片段计算稳定匹配等级：

1. 完整 canonical 名称；
2. 去掉 `$ctx$`、`$local$` 等前缀后的完整 path；
3. path 后缀；
4. 最后一个 path segment；
5. annotation 或 tag 的确定性词法命中。

候选按匹配等级和 Registry 原始顺序稳定排序，最多返回 `request.limit`。

### BO Field

每个 `PropertyTerm` 构造一个搜索文档，包含 BO 名、描述、tag、字段名和字段描述。先应用：

- `negative_keywords` 命中即排除；
- 字段名或字段描述 exact match 置顶；
- 明显的返回类型/基数冲突由现有候选硬校验继续负责。

对于剩余字段，批量生成资源向量；对 `keywords + aliases` 每个非空去重值分别生成查询向量：

```text
field_score = max(cosine(keyword_vector, field_vector))
```

向量层先取 Top 30，再与 exact/lexical 结果稳定融合，最终返回 `request.limit`。候选 `resource` 指向 canonical BO，`metadata["field"]` 指向 canonical Property。

### Function

Function 先按 Goal 的返回类型和 `is_list` 过滤。每个合法函数的搜索文档包含名称、描述、类别、tag、参数摘要和返回类型。

剩余函数采用与 BO Field 相同的独立关键词最大余弦分数，向量粗召回最多 20 个，再融合 exact/lexical 命中并截断到 `request.limit`。候选仍包含真实 `param_list`，最终选择只由 Coverage LLM 作出，余弦分数只作为 evidence/metadata。

### 降级与缓存

- embedding client 未配置或调用失败：回退到有界 exact/lexical 匹配；
- 向量数量、维度或数值非法：视为 embedding 失败；
- 查询向量在一次 Goal 内只计算一次；
- 搜索实例按资源搜索文本缓存资源向量；
- 降级时不得把整个 BO Field 或 Function Registry 直接发送给 LLM。

## 测试用例

### 编译检查

- 新增检索辅助结构可被导入；
- `OrchestratorResourceSearch` 不传 embedding client 时保持兼容；
- 现有 `ValueLogicGenerator` 与 Spec Orchestrator 构造路径无需修改公开输入输出。

### 自动化检查

- Context 名称/path 命中且不会调用 embedding；
- Context annotation/tag 仍可作为低优先级确定性候选；
- BO Field 对多个关键词分别计算并取最大余弦分数；
- BO Field 候选返回正确 BO 和 Property；
- exact 字段命中优先于纯向量命中；
- aliases 参与正向向量召回；
- negative keywords 确定性排除 BO Field 和 Function；
- Function 返回类型或基数不兼容时在 embedding 前排除；
- Function 向量结果仅形成候选并保留真实参数；
- embedding 失败时词法候选仍有界返回。

### 手工检查

使用“客户组名称”场景确认：

- `CUST_GRP_NAME` 命中 `BB_DIC_CUSTGRP` 的对应 Property；
- “客户组名称”与英文别名分别评分，任一高分均可召回该字段；
- `BuildCustGroupName` 只有返回类型兼容时进入 Function 候选；
- Coverage LLM 仍能拒绝语义相似但操作不合适的函数。

### 回归检查

- `tests/test_spec_orchestrator_search.py`；
- `tests/test_spec_orchestrator.py`；
- Spec Orchestration 相关测试集；
- 完整 pytest，区分本次改动失败与工作区已有未提交修改影响。
