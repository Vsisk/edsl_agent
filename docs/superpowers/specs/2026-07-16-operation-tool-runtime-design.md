# Operation Tool Runtime 统一工具编排设计

## 状态

本设计用于描述在现有 `operation_orchestration` 基础上引入统一工具注册层、可扩展 tool loop、多树 workspace 和可变搜索树。本文只定义目标架构、模型、边界和迁移路径，不直接实现代码。

## 背景

仓库当前已经有一套节点操作编排能力：

- `OperationGenerator`：根据用户 query 生成操作图，支持 `create_node`、`modify_node`、`generate_expression`、`delete_node`。
- `OperationLocator`：基于当前 EDSL 树索引和 LLM，从候选节点中选择目标位置。
- `OperationExecutor`：按依赖顺序执行操作，每次变更后重建索引。
- `OperationActionAdapter`：把编排层动作适配到 `GenerateNodeOperation`、`ModifyNodeOperation`、`ValueLogicGenerator` 和本地删除逻辑。

这套能力已经能覆盖一部分“根据 query 判断操作 + 定位节点 + 执行”的场景。但它目前是固定 operation graph 形态：LLM 一次性输出 operations，executor 再执行。对于多任务、跨树操作、扩展工具和边执行边确认位置的场景，tool loop 会更自然。

新的目标是把新增节点、修改节点、生成表达式、删除节点包装成可注册工具，并支持后续扩展工具；同时让搜索树可变，且支持两类树：

- `mapping_content` 树：当前 EDSL 工程映射树。
- `logic_area` 树：逻辑区域树。

## 目标

1. 提供统一 `OperationToolRegistry`，允许内置和扩展工具注册。
2. 提供 `OperationToolRuntime`，管理 tool loop 的状态、树 workspace、工具调用和 trace。
3. 支持多个可变树 workspace，每个工具调用都基于最新树版本。
4. 支持 `mapping_content` 和 `logic_area` 两类树，并允许未来增加新树类型。
5. 将现有 `operation_orchestration` 能力作为 `mapping_content` adapter 的底层实现复用。
6. LLM 只负责选择工具和填写受控参数，不直接输出 patch 或任意 JSONPath 修改。
7. 支持多任务：工具调用之间可以依赖上一步创建/修改/搜索出来的节点。
8. 每个 mutating tool 后重建对应树索引，后续搜索使用最新树。
9. 所有工具输出保留结构化 trace，便于调试、回放和失败诊断。

## 非目标

- 不让 LLM 直接修改树对象或直接返回可应用 patch。
- 不在第一阶段重写 `GenerateNodeOperation`、`ModifyNodeOperation`、`ValueLogicGenerator`。
- 不在第一阶段完整实现 logic area 的全部生成/修改规则；先定义统一接口和 adapter 边界。
- 不替换现有 `OperationOrchestrator`；它仍可作为 deterministic operation graph 路径保留。
- 不把工具注册层绑定到某一个 LLM SDK 或某一种 function calling 协议。

## 总体架构

```text
User Query
  -> OperationToolLoopAgent
       -> tool planning / tool call selection by LLM
       -> OperationToolRuntime
            -> OperationToolRegistry
            -> TreeWorkspaceStore
            -> Tool handlers
                 -> MappingContentToolAdapter
                 -> LogicAreaToolAdapter
       -> OperationToolLoopResponse
```

职责划分：

- `OperationToolRegistry`：注册工具的名称、描述、输入输出模型、handler、能力声明和适用树类型。
- `OperationToolRuntime`：持有多树状态，执行工具调用，做 schema 校验、权限校验、版本更新和 trace 记录。
- `TreeWorkspaceStore`：管理多个树 workspace，包括当前树版本、索引和变更历史。
- `OperationToolLoopAgent`：把用户 query、工具列表和当前状态发给 LLM，让 LLM 逐步选择工具。
- `ToolAdapter`：针对不同树类型实现搜索、创建、修改、删除、表达式生成等业务动作。

## 树模型

### TreeRef

```python
class TreeRef(BaseModel):
    tree_type: Literal["mapping_content", "logic_area"]
    tree_id: str | None = None
```

示例：

```json
{"tree_type": "mapping_content", "tree_id": null}
```

```json
{"tree_type": "logic_area", "tree_id": "LA_CHARGE"}
```

`tree_id` 用于区分多个逻辑区域树。`mapping_content` 通常只有一个主树，`tree_id` 可以为空。

### TreeWorkspace

```python
class TreeWorkspace(BaseModel):
    tree_ref: TreeRef
    tree: dict[str, Any]
    version: int = 0
    index_revision: int = 0
```

规则：

- mutating tool 执行成功后，`version += 1`。
- 索引基于当前 `version` 构建或缓存。
- tool 返回的 node ID 和 JSONPath 必须对应当前版本。
- 如果工具输入携带旧版本 location，runtime 必须重新校验，必要时要求重新搜索。

### OperationToolRuntimeState

```python
class OperationToolRuntimeState(BaseModel):
    trees: list[TreeWorkspace]
    active_tree: TreeRef
    variables: dict[str, Any] = {}
```

`variables` 用来保存 tool loop 中间结果，例如：

- 上一步 `create_node` 返回的 `created_node_id`
- 上一步 `search_nodes` 的候选 ID
- 某个树的最新 version

LLM 不直接写 `variables`，只能通过工具返回结果让 runtime 记录。

## 统一候选模型

不同树类型的索引结果需要归一化成统一候选：

```python
class NodeSearchCandidate(BaseModel):
    tree_ref: TreeRef
    node_id: str
    jsonpath: str
    node_type: str
    name: str | None = None
    annotation: str | None = None
    parent_node_id: str | None = None
    parent_name: str | None = None
    child_count: int = 0
    identity_field: Literal["node_id", "field_id"] | None = None
    field_slot: str | None = None
    score: float | None = None
```

`mapping_content` 可以由现有 `NodeLocateCandidate` 转换而来。`logic_area` 需要新增 `LogicAreaTreeIndexBuilder`，但也输出同一个候选模型。

## 工具注册层

### OperationToolSpec

```python
class OperationToolSpec(BaseModel):
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    mutates_tree: bool = False
    supported_tree_types: set[str] = {"mapping_content"}
    requires_location: bool = False
```

handler 不放进 Pydantic model，可由 registry 内部保存：

```python
ToolHandler = Callable[[BaseModel, ToolExecutionContext], BaseModel]
```

### OperationToolRegistry

```python
class OperationToolRegistry:
    def register(self, spec: OperationToolSpec, handler: ToolHandler) -> None: ...
    def get(self, name: str) -> RegisteredOperationTool: ...
    def list_tools(self, tree_ref: TreeRef | None = None) -> list[OperationToolSpec]: ...
```

注册规则：

- 工具名必须唯一。
- 工具名使用小写 snake_case。
- `input_model` 和 `output_model` 必须是严格 Pydantic 模型。
- registry 不执行业务逻辑，只做发现、schema 和 dispatch。
- 扩展工具只能通过 `register()` 进入 tool loop，不能直接访问 runtime 内部状态。

## 工具执行上下文

```python
class ToolExecutionContext(BaseModel):
    call_id: str
    state: OperationToolRuntimeState
    site_id: str | None = None
    project_id: str | None = None
    max_items: int = 50
```

handler 接收的是受控上下文视图。对树的实际写入由 runtime 完成，而不是 handler 随意原地修改全局状态。

推荐 handler 返回：

```python
class ToolResultEnvelope(BaseModel):
    output: BaseModel
    tree_updates: list[TreeUpdate] = []
```

第一阶段也可以简化为 handler 直接返回 output，并在 output 中约定 `updated_tree`；但最终应收敛到 runtime 统一提交树变更。

## 内置工具

### inspect_tree

用途：查看某棵树或某个节点。

输入：

```python
class InspectTreeInput(BaseModel):
    tree_ref: TreeRef | None = None
    jsonpath: str | None = None
    max_depth: int = 2
```

输出：

```python
class InspectTreeOutput(BaseModel):
    tree_ref: TreeRef
    version: int
    node: dict[str, Any]
```

规则：

- 未指定 `tree_ref` 时使用 active tree。
- 如果指定 `jsonpath`，必须能在当前版本解析。

### search_nodes

用途：在指定树中搜索操作位置。

输入：

```python
class SearchNodesInput(BaseModel):
    tree_ref: TreeRef | None = None
    query: str
    intent_type: Literal["create_node", "modify_node", "generate_expression", "delete_node"]
    limit: int = 20
```

输出：

```python
class SearchNodesOutput(BaseModel):
    tree_ref: TreeRef
    version: int
    candidates: list[NodeSearchCandidate]
```

规则：

- 使用当前 workspace 的最新树。
- 先按 intent 做结构过滤，再做语义排序。
- 对 `mapping_content`，第一阶段可复用 `build_node_index()` + `is_valid_candidate()` + `OperationLocator`。
- 对 `logic_area`，新增索引器后复用统一候选模型。

### create_node

输入：

```python
class CreateNodeInput(BaseModel):
    tree_ref: TreeRef | None = None
    parent_jsonpath: str
    query: str
```

输出：

```python
class CreateNodeOutput(BaseModel):
    tree_ref: TreeRef
    version: int
    created_node_id: str
    created_jsonpath: str
    node: dict[str, Any]
```

规则：

- `parent_jsonpath` 必须来自当前版本可解析位置。
- 父节点必须是该树类型允许的 create parent。
- `mapping_content` 复用 `GenerateNodeOperation`。
- `logic_area` 由 `LogicAreaToolAdapter.create_node` 实现。
- 成功后 runtime 更新对应 workspace tree，并重建索引。

### modify_node

输入：

```python
class ModifyNodeInput(BaseModel):
    tree_ref: TreeRef | None = None
    target_jsonpath: str
    query: str
```

输出：

```python
class ModifyNodeOutput(BaseModel):
    tree_ref: TreeRef
    version: int
    target_node_id: str
    target_jsonpath: str
    node: dict[str, Any]
```

规则：

- 第一阶段 `mapping_content` 可复用 `ModifyNodeOperation`。
- 需要扩展现有 modify 候选规则，允许 AB 内部 `field_id` 字段按工具能力修改。
- 对 `logic_area`，由专用 adapter 实现。

### generate_expression

输入：

```python
class GenerateExpressionInput(BaseModel):
    tree_ref: TreeRef | None = None
    target_jsonpath: str
    query: str
```

输出：

```python
class GenerateExpressionOutput(BaseModel):
    tree_ref: TreeRef
    version: int
    target_node_id: str
    expression: str
    return_type: dict[str, Any] | None
```

规则：

- 第一阶段主要支持 `mapping_content`。
- 复用 `ValueLogicGenerator`。
- 写回 simple leaf 的 `data_expression` 或 AB common field 的 expression branch。
- 不允许 LLM 直接生成 patch。

### delete_node

输入：

```python
class DeleteNodeInput(BaseModel):
    tree_ref: TreeRef | None = None
    target_jsonpath: str
```

输出：

```python
class DeleteNodeOutput(BaseModel):
    tree_ref: TreeRef
    version: int
    deleted_node_id: str
    parent_node_id: str | None
```

规则：

- 禁止删除 root。
- 删除对象必须是当前树中的 list element。
- `mapping_content` 复用现有 deterministic delete 逻辑。
- AB detail 被 summary 引用时继续禁止删除。

### switch_tree

输入：

```python
class SwitchTreeInput(BaseModel):
    tree_ref: TreeRef
```

输出：

```python
class SwitchTreeOutput(BaseModel):
    active_tree: TreeRef
```

规则：

- 只允许切换到 runtime 已注册 workspace。
- 不修改树。

### validate_tree

输入：

```python
class ValidateTreeInput(BaseModel):
    tree_ref: TreeRef | None = None
```

输出：

```python
class ValidateTreeOutput(BaseModel):
    valid: bool
    errors: list[dict[str, Any]]
```

规则：

- 每种树类型有自己的 validator。
- mapping_content 可复用现有 Pydantic 节点模型和 operation index 校验。
- logic_area 使用独立 schema。

## Tool Loop

### 请求模型

```python
class OperationToolLoopRequest(BaseModel):
    query: str
    trees: list[TreeWorkspace]
    active_tree: TreeRef = TreeRef(tree_type="mapping_content")
    site_id: str | None = None
    project_id: str | None = None
    max_steps: int = 20
```

### 响应模型

```python
class ToolCallTrace(BaseModel):
    step: int
    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    success: bool
    error_message: str | None = None
    tree_versions_before: dict[str, int]
    tree_versions_after: dict[str, int]


class OperationToolLoopResponse(BaseModel):
    success: bool
    trees: list[TreeWorkspace]
    active_tree: TreeRef
    calls: list[ToolCallTrace]
    error_message: str | None = None
```

### 执行流程

```text
1. 初始化 runtime state 和 tool registry。
2. 渲染可用工具列表、用户 query、当前 active tree 摘要。
3. LLM 输出下一步 tool call。
4. runtime 校验 tool name 和 input schema。
5. tool handler 执行，必要时更新 tree workspace。
6. runtime 记录 trace。
7. 如果 LLM 判断任务完成，输出 final response。
8. 达到 max_steps 或工具失败不可恢复时停止。
```

LLM 的职责：

- 决定下一步调用哪个工具。
- 在工具返回候选后选择下一步位置。
- 对多任务维护自然语言层面的任务进度。

runtime 的职责：

- 校验 tool 输入输出。
- 校验 JSONPath 是否真实存在。
- 校验操作是否适用于目标树和目标节点。
- 应用树变更。
- 重建索引。
- 记录 trace。

## 多任务支持

示例 query：

```text
新增费用信息节点，下面新增费用金额字段，并生成取费用金额字符串的表达式。
```

可能的 tool loop：

```text
1. search_nodes(intent=create_node, query="费用信息父节点")
2. create_node(parent_jsonpath="$", query="新增费用信息节点，需要包含子节点")
3. create_node(parent_jsonpath="<费用信息节点路径>", query="新增费用金额字段")
4. generate_expression(target_jsonpath="<费用金额字段路径>", query="取费用金额字符串")
5. validate_tree()
```

多任务不是一次性要求 LLM 输出完整 operation graph。LLM 可以根据每一步工具结果继续决策。这样更适合：

- 新增多个兄弟节点。
- 新增父节点后再新增子节点。
- 修改已有节点后再生成表达式。
- 同时操作 mapping_content 和 logic_area。

## 双树支持

### mapping_content 树

第一阶段完整支持。可复用：

- `operation_orchestration.node_index.build_node_index`
- `operation_orchestration.locator.OperationLocator`
- `GenerateNodeOperation`
- `ModifyNodeOperation`
- `ValueLogicGenerator`
- `OperationActionAdapter` 中的 delete / expression write-back 逻辑

需要补的能力：

- 将现有 candidate 转成统一 `NodeSearchCandidate`。
- 将现有 action adapter 拆成 `MappingContentToolAdapter`。
- 支持修改 AB 内部 `field_id` 字段。

### logic_area 树

第一阶段定义接口，第二阶段实现。

需要新增：

- `LogicAreaTreeIndexBuilder`
- `LogicAreaToolAdapter`
- logic area 节点 validator
- logic area create/modify/delete 规则

logic_area adapter 对外仍输出统一工具模型，不影响 tool loop 主流程。

## 安全边界

1. LLM 不直接输出 patch。
2. LLM 不直接写 runtime state。
3. LLM 选择的 JSONPath 必须来自工具返回候选，且运行时重新校验。
4. 所有 mutating tool 必须在 deep copy 上构造更新，成功后由 runtime 提交。
5. 工具调用必须声明 `tree_ref` 或使用 active tree。
6. 每次树变更后必须重建索引。
7. create/modify/delete/generate_expression 必须按树类型和节点类型做能力校验。
8. 工具 handler 异常不会泄露敏感堆栈到 LLM，只返回稳定错误码和摘要。
9. tool loop 有 `max_steps`，避免无限循环。
10. 所有工具调用记录 trace，支持回放和诊断。

## 与现有 operation_orchestration 的关系

保留现有 `OperationOrchestrator`：

- 适合一次性 operation graph。
- 测试覆盖充分。
- 可作为 deterministic baseline。

新增 `OperationToolRuntime`：

- 适合多任务、跨树、需要边执行边定位的场景。
- 使用现有 operation capabilities 作为底层 adapter。
- 不破坏现有 API。

迁移方式：

```text
Phase 1:
  OperationToolRegistry + mapping_content tools

Phase 2:
  Tool loop agent + trace + max_steps

Phase 3:
  logic_area tree workspace + adapter

Phase 4:
  AB 内部字段 modify/create slot 细化

Phase 5:
  将外部入口逐步切到 tool loop，OperationOrchestrator 保留为兼容路径
```

## 推荐目录结构

```text
agent/operation_tools/
  __init__.py
  models.py
  registry.py
  runtime.py
  tool_loop.py
  adapters/
    __init__.py
    mapping_content.py
    logic_area.py
  indexing/
    __init__.py
    mapping_content.py
    logic_area.py
  tools/
    __init__.py
    inspect.py
    search.py
    create_node.py
    modify_node.py
    generate_expression.py
    delete_node.py
    switch_tree.py
    validate_tree.py
```

## 测试策略

### Registry

- 注册工具成功。
- 重复工具名失败。
- 按 tree type 过滤工具。
- schema 校验失败时不调用 handler。

### Runtime

- active tree 默认值。
- switch tree。
- mutating tool 更新 version。
- mutating tool 后 search 使用最新树。
- 工具失败记录 trace 且不提交 tree update。

### mapping_content adapter

- search_nodes 复用现有 DFS index。
- create_node 调用 `GenerateNodeOperation` 并返回 created JSONPath。
- modify_node 修改 simple leaf。
- modify_node 支持 AB field_id。
- generate_expression 写回 simple leaf 和 AB common field。
- delete_node 禁止 root，禁止删除被 summary 引用 detail field。

### logic_area adapter

- 索引 logic area 节点。
- create/modify/delete 的最小 happy path。
- invalid schema 失败。

### Tool loop

- 单步新增节点。
- 新增父节点 + 新增子节点。
- 修改已有节点。
- 生成表达式。
- 删除节点。
- 跨 mapping_content 和 logic_area 的多任务。
- max_steps 终止。
- 工具返回候选后下一步使用候选位置。

### 回归

- 现有 `operation_orchestration` 测试保持通过。
- 现有 generate/modify/expression 测试保持通过。

## 开放问题

1. logic_area 树的 canonical schema 是否已经稳定。
2. logic_area 节点是否也需要 `node_id`/`field_id` 双身份。
3. AB 内部字段 modify 是否复用 `ModifyNodeOperation`，还是新增 AB field 专用 modifier。
4. tool loop 的 LLM 输出协议使用 OpenAI tools/function calling，还是保持本地抽象后由调用方适配。
5. 是否需要提供 transaction/rollback；第一阶段建议不做，只保留 fail-fast 和 trace。

## 完成标准

1. 所有内置工具通过 `OperationToolRegistry` 注册。
2. tool loop 能在 mapping_content 树上完成 create/modify/generate_expression/delete。
3. 每次 mutate 后 search 基于最新树版本。
4. 工具调用 trace 完整记录输入、输出、版本变化和错误。
5. LLM 无法直接提交 patch 或伪造 JSONPath。
6. logic_area 树通过同一 workspace 和工具协议接入。
7. 现有 operation orchestration 和 value generation 测试不回退。
