# Operation Tool Loop 第一阶段设计

## 范围

第一阶段只改造 `mapping_content`。`logic_area`、多树 workspace、`switch_tree` 和跨树任务放到第二阶段。

现有 `operation_orchestration` 原地改造成 tool loop，不新增一套平行的 `operation_tools` 包。默认入口仍为 `OperationOrchestrator.run(query, target_tree, site_id, project_id)`，返回仍兼容 `ExecuteOperationsResponse`。

## 关键决策

1. 默认主流程不再先生成完整 operation graph。LLM 每轮只选择一个工具或声明完成，运行时执行后把结构化结果放回下一轮上下文。
2. 内置工具通过 `OperationToolRegistry` 统一注册，第一阶段包含 `search_nodes`、`create_node`、`modify_node`、`generate_expression`、`delete_node` 和 `finish`。
3. 搜索复用 `build_node_index()` 和 `is_valid_candidate()`。候选保留已有 `node_id`、`field_id`、JSONPath、节点类型和父节点信息。
4. 变更复用 `OperationActionAdapter`，底层继续调用 `GenerateNodeOperation`、`ModifyNodeOperation` 和 `ValueLogicGenerator`。
5. LLM 不能直接修改树。变更工具必须引用最近一次 `search_nodes` 返回的候选，并同时匹配候选 ID、JSONPath、意图和当前树版本。
6. 每次成功变更后使用返回树重建索引，树版本加一，并清空旧搜索授权。后续步骤只能搜索和操作最新树。
7. 每个成功变更工具对应一个已执行的 `Operation`，从而保留现有响应里的 operation 诊断信息。
8. 工具调用全程记录结构化 trace。失败时保留最后一次成功提交的树，当前工具记录稳定错误，后续工具不再执行。
9. `max_steps` 限制循环。只有显式 `finish` 才视为成功；超过上限返回结构化失败。

## 组件

### OperationToolRegistry

注册工具名称、描述、严格 Pydantic 输入模型、是否修改树及 handler。它负责唯一性校验、工具发现和 dispatch，不持有树状态。

### OperationToolRuntime

持有当前 `mapping_content` 私有副本、版本、最新索引、搜索授权、已执行 operations 和调用 trace。它负责输入校验、候选授权校验、变更提交、索引刷新和错误隔离。

### OperationToolLoop

向 LLM 提供用户 query、当前树摘要、工具 schema 和历史调用。每轮严格解析一个 `tool_name + arguments` 决策，交给 runtime 执行，直到 `finish`、失败或达到 `max_steps`。

### OperationOrchestrator

默认委托 `OperationToolLoop`。为已有注入式测试和调用方保留显式 legacy `generator + executor` 兼容路径，但生产默认构造不再创建 operation graph generator。

## 数据流

```text
query + mapping_content
  -> OperationOrchestrator
  -> OperationToolLoop
  -> LLM next-tool decision
  -> OperationToolRegistry
  -> OperationToolRuntime
       search_nodes -> current index candidates + authorization
       mutating tool -> OperationActionAdapter -> validate -> commit -> reindex
  -> next LLM round
  -> finish
  -> ExecuteOperationsResponse + tool trace
```

## 错误处理

- 非法工具名、额外参数或字段类型错误：当前调用失败，不执行 handler。
- 未搜索、伪造、混合或过期的候选位置：拒绝变更。
- adapter 异常、返回树非法、输出节点不存在：不提交尝试中的树。
- LLM gateway 或决策结构错误：返回稳定错误，不泄漏底层异常和敏感内容。
- 达到 `max_steps`：失败并返回已提交树与完整 trace。

## 测试边界

1. registry 注册、重复注册、schema 校验和工具枚举。
2. search 只返回当前意图允许的候选，并产生当前版本授权。
3. create/modify/generate/delete 复用 adapter，提交后版本递增并重建索引。
4. 未搜索、伪造路径和旧版本候选不能执行。
5. tool loop 支持单任务和多任务，逐步使用新建节点。
6. `finish`、工具失败、LLM 失败和 `max_steps` 都产生稳定响应与 trace。
7. 现有 operation generator、locator、executor、action adapter 测试保持通过。

## 第二阶段

第二阶段再引入 `TreeRef`、多树 workspace、`logic_area` 索引与 adapter、`switch_tree` 以及跨树 tool loop。第一阶段模型不提前暴露未实现的 logic area 分支。
