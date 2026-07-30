# ResourceTypeAwareRetrieval_20260730

## 核心功能（WHAT）

将 `OrchestratorResourceSearch` 当前统一的关键词包含匹配改为按资源类型分流的候选召回：

- Context 根据 canonical 名称或 path 做确定性匹配；
- BO Field 以单个 `PropertyTerm` 为召回粒度，只比较 Property Name 与关键词、别名，不使用 embedding，并返回对应 BO 与 Property；
- Function 先按返回类型和基数做硬过滤，再用独立关键词余弦评分做粗召回，最终仍由现有 LLM Coverage Decision 根据完整 query 选择。

`keywords` 和 `aliases` 参与正向召回；`negative_keywords` 仅用于确定性排除，不参与负向向量计算。

### 需求背景（WHY）

当前 `agent/spec_orchestration/search.py` 使用 `_matches()` 统一搜索 Context、BO Field 和 Function。统一的子串匹配无法稳定覆盖中文业务语义、英文缩写和字段别名，也忽略了不同资源的固有约束：

- Context 已有 canonical 名称和作用域 path，语义向量可能引入不必要的误召回；
- BO 的真正目标是某个 `property_list` 字段，而不是整个 BO；
- Function 名称相似不代表操作语义相同，且函数能否覆盖 Goal 首先受返回类型、基数和真实参数约束。

### 需求目标（GOAL）

1. Context 搜索只返回名称或 path 可确定性命中的可见 canonical 资源。
2. BO Field 对每个字段分别召回，候选包含真实 `BoRegistry` 和 `PropertyTerm`。
3. BO Field 对 Property Name 与关键词、别名做大小写、下划线归一化匹配，并使用 camelCase/snake_case 分词后的词法余弦补充召回。
4. Function 在向量召回前完成返回类型和基数过滤，向量结果只负责压缩几百个函数形成的候选池。
5. 所有候选继续交给现有 Coverage LLM 做最终语义判断，并由代码执行 canonical、类型和依赖校验。
6. Embedding 异常时使用有界词法召回，不向 LLM 暴露全量 Registry。

### 范围边界

纳入范围：

- `VISIBLE_VALUE`、`BO_FIELD`、`FUNCTION` 三个搜索层；
- Function 的 embedding client 注入、分批向量计算、余弦排序和失败降级；
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
  ├─ BO_FIELD      → Property Name deterministic matcher
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

BO Field 不构造 embedding 文档。代码遍历每个 BO 的 `property_list`，只对 `field_name` 与 `keywords + aliases` 做确定性匹配：

1. 大小写归一化后完整相等；
2. 移除下划线后完整相等；
3. 移除下划线后互为后缀。
4. camelCase、snake_case、空格文本分词后的软词项余弦相似度不低于 0.75。

软词项余弦对完全相同 token 计 1.0；长度不少于 3 的有序缩写按长度比例计分，例如 `grp` 可与 `group` 匹配。候选先按匹配等级、再按余弦分数、最后按 Registry 原始顺序稳定排序。

`negative_keywords` 使用相同的 Property Name 匹配规则并优先排除。BO 描述、tag、字段描述和 Goal 自由文本不参与 BO Field 召回。`resource` 指向 canonical BO，`metadata["field"]` 指向 canonical Property，并记录 `lexical_cosine_similarity`。BO Field 搜索不得调用 embedding client。

### Function

Function 先按 Goal 的返回类型和 `is_list` 过滤。每个合法函数的搜索文档包含名称、描述、类别、tag、参数摘要和返回类型。

剩余函数对每个关键词独立计算余弦相似度并取最大分数，向量粗召回最多 20 个，再融合 exact/lexical 命中并截断到 `request.limit`。资源 batch size 优先取 embedding client settings 的 `local_embedding_batch_size`，显式构造参数可覆盖；无 settings 时默认 64。候选仍包含真实 `param_list`，最终选择只由 Coverage LLM 作出，余弦分数只作为 evidence/metadata。

### 降级与缓存

- embedding client 未配置或调用失败：回退到有界 exact/lexical 匹配；
- 向量数量、维度或数值非法：视为 embedding 失败；
- 查询向量在一次 Goal 内只计算一次；
- 未缓存 Function 按配置的 batch size 分批调用 embedding client；
- 搜索实例按 Function 搜索文本缓存资源向量；
- 降级时不得把整个 Function Registry 直接发送给 LLM。

## 测试用例

### 编译检查

- 新增检索辅助结构可被导入；
- `OrchestratorResourceSearch` 不传 embedding client 时保持兼容；
- 现有 `ValueLogicGenerator` 与 Spec Orchestrator 构造路径无需修改公开输入输出。

### 自动化检查

- Context 名称/path 命中且不会调用 embedding；
- Context annotation/tag 仍可作为低优先级确定性候选；
- BO Field 只匹配 Property Name 且不会调用 embedding；
- `custGrpName` 可以被 `cust group name` 通过分词和词法余弦召回；
- BO Field 候选返回正确 BO 和 Property；
- Property Name exact 命中优先于去下划线和后缀命中；
- aliases 参与正向向量召回；
- negative keywords 确定性排除 BO Field 和 Function；
- Function 返回类型或基数不兼容时在 embedding 前排除；
- Function 向量结果仅形成候选并保留真实参数；
- embedding 失败时词法候选仍有界返回。

### 手工检查

使用“客户组名称”场景确认：

- `CUST_GRP_NAME` 命中 `BB_DIC_CUSTGRP` 的对应 Property；
- `CUST_GRP_NAME` 或规范化后的字段别名可以召回该字段；
- `BuildCustGroupName` 只有返回类型兼容时进入 Function 候选；
- Coverage LLM 仍能拒绝语义相似但操作不合适的函数。

### 回归检查

- `tests/test_spec_orchestrator_search.py`；
- `tests/test_spec_orchestrator.py`；
- Spec Orchestration 相关测试集；
- 完整 pytest，区分本次改动失败与工作区已有未提交修改影响。
