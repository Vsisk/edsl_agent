# EDSL 节点生成与修改规格设计

## 1. 文档状态

- 文档类型：技术规格与设计说明
- 适用范围：`GenerateNodeOperation`、`ModifyNodeOperation`
- 规范版本：1.0
- 语义策略：LLM-only，不提供生产关键词回退
- 目标读者：EDSL 生成链路开发者、测试人员、集成调用方

本文档是节点生成与修改能力的统一现行规范。此前的 GenerateNode、ModifyNode 及 LLM 驱动改造文档保留为设计演进记录；若其内容与本文冲突，以本文为准。

## 2. 背景与目标

EDSL tree 由不同类型的 `TreeNodeTerm` 组成。上游会把用户需求拆分到单节点粒度，但自然语言仍然不能直接作为节点 JSON 或 JSON Patch 使用。系统需要在 LLM 语义理解与本地结构安全之间建立明确边界。

本设计提供两个 operation：

- `GenerateNodeOperation`：根据单节点 query 和目标父路径生成一个新节点，并返回 add patch。
- `ModifyNodeOperation`：根据单节点 query 和目标节点路径修改现有节点，必要时执行完整类型迁移，并返回 replace patch。

共同目标：

1. 使用 LLM 处理节点类型、字段含义、生成意图和修改意图等语义任务。
2. 使用 Pydantic 模型约束所有 LLM 输出，不允许 LLM 直接生成最终节点或 patch。
3. 复用现有 `TreeNodeTerm` 及其关联模型，不重复定义 EDSL schema。
4. 把路径解析、字段白名单、默认值、迁移规则、破坏性保护、最终校验和 patch 构造保留在本地代码。
5. 所有失败均返回结构化错误；失败结果不得携带可应用 patch。

## 3. 非目标

本设计不负责：

- 拆分包含多个节点的自然语言需求。
- 让 LLM 直接生成完整 `TreeNodeTerm` JSON。
- 让 LLM 直接生成 RFC 6902 patch。
- 重构现有 expression generator、resource manager 或 planner 的核心逻辑。
- 支持任意 JSONPath 表达式。
- 自动应用 patch 或原地修改输入 EDSL tree。
- 为复杂 data source 或 AB content 编造缺失结构。

## 4. 核心设计原则

### 4.1 LLM 负责语义，本地代码负责结构

LLM 负责：

- 新节点类型判断。
- 新节点公共字段生成。
- 新节点类型专属内容意图判断。
- 修改意图分类。
- 结构化修改计划生成。

本地代码负责：

- JSONPath 解析与 JSON Pointer 构造。
- 目标节点和父节点存在性校验。
- 节点类型可用字段白名单。
- 类型专属默认模型实例化。
- 节点类型迁移矩阵。
- 破坏性风险计算和外部授权开关。
- `TreeNodeTerm.model_validate()`。
- AB 内外类型一致性。
- RFC 6902 add/replace patch 构造。

### 4.2 多阶段窄调用

每个 prompt 只完成一个职责。禁止单个 prompt 同时进行类型判断、字段生成、节点组装和 patch 构造。

### 4.3 无关键词回退

生产代码不使用关键词表、中文名称映射表或正则表达式解释节点语义。LLM 不可用、调用异常、JSON 非法或 Pydantic 校验失败时，operation 直接返回对应结构化错误，不重试、不回退关键词规则。

资源搜索子系统中的显式关键词检索不在本规范的删除范围内，因为它属于资源定位，不属于节点意图分类。

### 4.4 完整节点校验

无论是生成、局部修改还是类型迁移，候选结果最终都必须构造成完整节点并通过：

```python
TreeNodeTerm.model_validate(candidate)
```

模型负责默认值补全、非法类型字段清理及 AB discriminator 修复。

## 5. 复用模型

节点结构以项目根目录 `models.py` 为唯一 schema 来源，主要复用：

- `TreeNodeTerm`
- `XmlNamePropertyTerm`
- `DataExpressionTerm`
- `DataTypeTerm`
- `DataSourceTerm`
- `SupportBigCustAcctTerm`
- `SingleMappingTableTerm`
- `PivotTableTerm`
- `TwoLevelTableTerm`
- `EdslSemiStructTerm`
- `EdslPromptTerm`

### 5.1 公共字段

所有节点共有：

```text
node_id
xml_name_property
annotation
edsl_semi_struct
edsl_prompt
tree_node_type
reference_logic_area_id_list
```

其中 `node_id`、`edsl_semi_struct`、`edsl_prompt` 只能由本地模型默认值或本地逻辑生成，不能交给 LLM 决定。

### 5.2 类型字段白名单

| `tree_node_type` | 允许的类型字段 |
|---|---|
| `simple_leaf` | `data_expression`、`data_type_config`、`support_big_cust_acct` |
| `parent` | `children`、`local_context` |
| `parent_list` | `data_source`、`support_big_cust_acct`、`children`、`local_context`、`iter_local_context` |
| `ab_single_mapping_table` | `ab_content` |
| `ab_pivot_table` | `ab_content` |
| `ab_two_level_table` | `ab_content` |

`TreeNodeTerm.adjust_for_node_type` 的可选字段全集必须包含：

```python
{
    "data_expression",
    "data_type_config",
    "children",
    "ab_content",
    "local_context",
    "iter_local_context",
    "data_source",
    "support_big_cust_acct",
}
```

`special_configs` 必须通过 factory 生成 list 和模型默认值，禁止跨节点共享可变对象。

## 6. 路径与 Patch 规范

### 6.1 支持的路径

operation 接收简单 JSONPath：

```text
$.mapping_content
$.mapping_content.children[0]
mapping_content.children[1]
```

未以 `$` 开头的路径统一补全为 `$.`。

只支持：

- 普通对象字段。
- 非负整数数组索引。

不支持：

- wildcard。
- filter。
- slice。
- recursive descent。
- 一次匹配多个节点的表达式。

### 6.2 JSON Pointer

JSONPath 会转换为 RFC 6901 JSON Pointer：

```text
$.mapping_content.children[0]
-> /mapping_content/children/0
```

### 6.3 Patch 不变量

- Generate 使用单个 RFC 6902 `add` patch，目标为父节点 `children/-`。
- Modify 使用单个 RFC 6902 `replace` patch，目标为完整节点。
- operation 不修改输入 tree。
- 失败结果不得包含 patch。

## 7. LLM 网关与通用失败策略

默认 LLM 网关使用：

```python
generate_by_llm(prompt_key, **prompt_variables)
```

各语义组件允许注入 callable，用于单元测试或替换调用实现。注入 callable 的输入必须与对应 prompt 的语义输入一致。

调用流程：

```text
构造 prompt variables
  -> generate_by_llm / injected gateway
  -> JSON dict
  -> Pydantic model_validate
  -> 本地流程消费
```

以下情况均视为该语义阶段失败：

- LLM 配置不可用。
- 网络、鉴权或超时异常。
- 响应不是合法 JSON object。
- 缺少必填字段。
- 枚举值不合法。
- 输出类型与前序阶段矛盾。

组件捕获底层异常后，抛出本组件的 `OperationFailure`；原始异常通过 exception chaining 保留，不对用户输出敏感连接信息。

## 8. GenerateNodeOperation 规格

### 8.1 输入

```python
class GenerateNodeOperationInput(BaseModel):
    query: str
    node_path: str
    edsl_tree: dict[str, Any]
    debug: bool = False
```

`node_path` 表示目标父节点路径。上游保证 `query` 只描述一个新节点。

### 8.2 输出

```python
class GenerateNodeOperationOutput(BaseModel):
    success: bool
    operation_type: Literal["generate_node"] = "generate_node"
    node_path: str
    parent_path: str | None = None
    children_path: str | None = None
    generated_node: dict[str, Any] | None = None
    patch: dict[str, Any] | None = None
    route_result: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    failure_reason: str | None = None
```

成功时：

- `generated_node` 存在。
- `patch` 存在且可应用。
- `failure_reason` 为空。

失败时：

- `generated_node` 为空。
- `patch` 为空。
- `failure_reason` 和 `validation_errors` 描述失败。

### 8.3 主流程

```text
GenerateNodeOperationInput
  -> PathResolver
  -> NodeTypeRouter (LLM)
  -> CommonFieldGenerator (LLM)
  -> NodeContentIntentGenerator (LLM)
  -> TypeSpecificFieldGenerator (local)
  -> NodeAssembler (local)
  -> TreeNodeTerm.model_validate (local)
  -> NodePatchBuilder (local)
  -> GenerateNodeOperationOutput
```

### 8.4 父节点校验

允许承载 `children` 的目标父类型：

- `parent`
- `parent_list`

以下类型不能作为新增子节点的父容器：

- `simple_leaf`
- `ab_single_mapping_table`
- `ab_pivot_table`
- `ab_two_level_table`

### 8.5 节点类型路由

生成 operation 只允许生成：

```text
simple_leaf
parent
parent_list
ab_pivot_table
ab_two_level_table
```

LLM 输出模型：

```python
class NodeRouteResult(BaseModel):
    tree_node_type: Literal[
        "simple_leaf",
        "parent",
        "parent_list",
        "ab_pivot_table",
        "ab_two_level_table",
    ]
    confidence: float = 1.0
    reason: str
    evidence_terms: list[str] = Field(default_factory=list)
    source: Literal["local", "llm"] = "local"
```

模型默认值用于兼容构造；生产 `NodeTypeRouter` 在成功校验 LLM 输出后会把 `source` 设置为 `llm`。

### 8.6 公共字段生成

`CommonFieldGenerator` 只接受并返回：

```python
class CommonNodeFields(BaseModel):
    xml_name_property: XmlNamePropertyTerm
    annotation: str = ""
    reference_logic_area_id_list: list[str] = Field(default_factory=list)
```

约束：

- `xml_name` 必须非空。
- `xml_format_type` 只能为 `label` 或 `property`。
- `xml_empty_field_type` 只能为 `none`、`half` 或 `full`。
- 无明确 logic area ID 时返回空数组。
- 不接受 `node_id`、`edsl_semi_struct`、`edsl_prompt` 或类型专属字段。

### 8.7 内容生成意图

```python
class NodeContentIntent(BaseModel):
    tree_node_type: NodeType
    data_type: Literal["simple_string", "time", "money"] = "simple_string"
    requires_expression_generation: bool = False
    requires_data_source_generation: bool = False
    expression_query: str | None = None
    data_source_query: str | None = None
    ab_content_query: str | None = None
    reason: str = ""
```

`NodeContentIntent.tree_node_type` 必须与 `NodeTypeRouter` 结果一致，否则返回 `NODE_CONTENT_INTENT_FAILED`。

### 8.8 类型专属字段

`TypeSpecificFieldGenerator` 只消费结构化 `NodeContentIntent`，不读取 query 关键词。

| 类型 | 初始化行为 |
|---|---|
| `simple_leaf` | `DataExpressionTerm()`、`DataTypeTerm(intent.data_type)`、`SupportBigCustAcctTerm()` |
| `parent` | `children=[]`、`local_context=[]` |
| `parent_list` | `DataSourceTerm()`、`SupportBigCustAcctTerm()`、`children=[]`、`local_context=[]`、`iter_local_context=[]` |
| `ab_pivot_table` | `PivotTableTerm()` 作为 `ab_content` |
| `ab_two_level_table` | `TwoLevelTableTerm()` 作为 `ab_content` |

当前版本中，`TypeSpecificFieldGenerator` 使用 `data_type` 并为 expression、data source、AB content 初始化合法空壳；`requires_*` 和对应 query 字段作为后续 adapter 接入点保留。系统不得根据这些字段自行编造复杂结构。

### 8.9 Generate Patch

父路径：

```text
$.mapping_content
```

输出：

```json
{
  "op": "add",
  "path": "/mapping_content/children/-",
  "value": {"tree_node_type": "simple_leaf"}
}
```

`value` 实际为完整、已校验、已序列化的节点。

### 8.10 Generate 错误码

| 错误码 | 含义 |
|---|---|
| `INVALID_NODE_PATH` | 路径语法不支持或匹配不唯一 |
| `TARGET_PARENT_NOT_FOUND` | 目标父节点不存在 |
| `TARGET_PARENT_CANNOT_HAVE_CHILDREN` | 目标类型不能承载 children |
| `NODE_TYPE_ROUTE_FAILED` | 节点类型 LLM 调用或输出校验失败 |
| `COMMON_FIELD_GENERATION_FAILED` | 公共字段 LLM 调用或输出校验失败 |
| `NODE_CONTENT_INTENT_FAILED` | 内容意图 LLM 调用或输出校验失败 |
| `TYPE_SPECIFIC_FIELD_MISSING` | 目标类型必需字段未生成 |
| `NODE_SCHEMA_VALIDATION_FAILED` | 最终节点 Pydantic 校验失败 |

## 9. ModifyNodeOperation 规格

### 9.1 输入

```python
class ModifyNodeOperationInput(BaseModel):
    query: str
    node_path: str
    edsl_tree: dict[str, Any]
    site_id: str | None = None
    project_id: str | None = None
    debug: bool = False
    allow_destructive: bool = False
```

`node_path` 表示目标节点自身路径，不是父路径。

### 9.2 输出

```python
class ModifyNodeOperationOutput(BaseModel):
    success: bool
    operation_type: Literal["modify_node"] = "modify_node"
    node_path: str
    original_node: dict[str, Any] | None = None
    modified_node: dict[str, Any] | None = None
    patch_list: list[dict[str, Any]] = Field(default_factory=list)
    modify_intent: dict[str, Any] | None = None
    migration_report: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    failure_reason: str | None = None
```

成功时必须包含：

- `original_node`
- `modified_node`
- 非空 `patch_list`

失败时：

- 路径已解析时可保留 `original_node`。
- `modified_node` 必须为空。
- `patch_list` 必须为空。

### 9.3 主流程

```text
ModifyNodeOperationInput
  -> NodeResolver
  -> ModifyIntentRouter (LLM)
  -> ModifyPlanGenerator (LLM)
  -> MigrationPlanner (type change only, local)
  -> ModifyExecutor (local + adapters)
  -> DestructiveChangeGuard (local)
  -> TreeNodeTerm.model_validate (local)
  -> SemanticValidator (local)
  -> ModifyPatchBuilder (local)
  -> ModifyNodeOperationOutput
```

### 9.4 目标与上下文解析

`NodeResolver` 返回：

```text
node_path
node_pointer
current_node
parent_node
ancestor_nodes
visible_local_context
```

可见上下文从祖先和当前容器节点的 `local_context`、`iter_local_context` 中收集。解析结果可供 expression/data source adapter 使用。

### 9.5 修改意图

```python
class ModifyIntent(BaseModel):
    intent_type: Literal[
        "set_common_field",
        "modify_expression",
        "modify_datatype",
        "modify_data_source",
        "modify_context",
        "modify_ab_content",
        "change_node_type",
        "mixed",
    ]
    target_tree_node_type: Literal[
        "parent",
        "simple_leaf",
        "parent_list",
        "ab_pivot_table",
        "ab_two_level_table",
        "ab_single_mapping_table",
    ] | None = None
    affected_fields: list[str] = Field(default_factory=list)
    requires_expression_generation: bool = False
    requires_resource_selection: bool = False
    destructive_risk: bool = False
    reason: str = ""
```

该阶段只判断“用户想修改什么”，不能输出最终节点或 patch。

### 9.6 修改计划

```python
class NodeModifyPlan(BaseModel):
    intent: ModifyIntent
    common_field_updates: dict[str, Any] = Field(default_factory=dict)
    type_field_updates: dict[str, Any] = Field(default_factory=dict)
    expression_update_query: str | None = None
    datatype_update_query: str | None = None
    data_source_update_query: str | None = None
    ab_content_update_query: str | None = None
    migration_plan: NodeTypeMigrationPlan | None = None
    destructive_authorized: bool = False
    rebuild_node: bool = False
```

本地 allowlist：

- `common_field_updates` 只允许 `xml_name_property`、`annotation`、`reference_logic_area_id_list`。
- `type_field_updates` 只允许当前 `tree_node_type` 的类型字段。
- 在 `common_field_updates` 中夹带 `node_id` 等字段必须返回 `UNSUPPORTED_FIELD_UPDATE`。

`destructive_authorized` 只表示 LLM 判断用户是否在 query 中明确授权删除、清空、覆盖、丢弃或重建；它不能替代外部 `allow_destructive` 开关。

### 9.7 局部修改

局部修改在原节点深拷贝上应用：

- 公共字段按 allowlist 合并。
- `data_type_config` 使用 `DataTypeTerm.model_validate()` 校验。
- expression 通过 expression adapter 生成。
- data source 通过 data-source adapter 生成。
- AB content 通过 AB-content adapter 生成。
- 无 adapter 的复杂修改返回明确错误，不生成半成品。

最终仍校验完整 `TreeNodeTerm`。

### 9.8 Expression Adapter

默认 `ExistingExpressionAdapter` 复用现有 `ValueLogicGenerator`，输入上下文包括：

```text
query
node_path
current_node
parent_node
ancestor_nodes
visible_local_context
edsl_tree
site_id
project_id
```

缺少必需项目上下文或 expression generator 未返回 expression 时，返回 `EXPRESSION_GENERATION_FAILED`。

### 9.9 类型迁移

类型变化必须生成完整 `NodeTypeMigrationPlan`，不得只替换 `tree_node_type`。

默认保留基础字段：

```text
node_id
xml_name_property
annotation
edsl_semi_struct
edsl_prompt
reference_logic_area_id_list
```

只有 `NodeModifyPlan.rebuild_node=True` 时才调用 `TreeNodeTerm.update_id()`。

#### 9.9.1 迁移矩阵

| 源类型 | 目标类型 | 策略 |
|---|---|---|
| `parent` | `parent_list` | 保留 `children`、`local_context`；初始化 list 专属字段 |
| `parent_list` | `parent` | 保留 `children`、`local_context`；删除 `data_source`、`support_big_cust_acct`、`iter_local_context` |
| `simple_leaf` | `parent` | 删除 leaf 字段；初始化空 `children`、`local_context` |
| `simple_leaf` | `parent_list` | 删除 leaf 字段；初始化全部 list 字段 |
| `parent`/`parent_list` | `simple_leaf` | 删除容器字段；存在 children 时属于破坏性迁移 |
| `simple_leaf` | `ab_pivot_table` | 删除 leaf 字段；初始化 `PivotTableTerm` |
| `simple_leaf` | `ab_two_level_table` | 删除 leaf 字段；初始化 `TwoLevelTableTerm` |
| `ab_pivot_table` | `ab_two_level_table` | 重建 AB content；保留兼容 `data_source`、`group_by_fields` |
| `ab_two_level_table` | `ab_pivot_table` | 重建 AB content；保留兼容 `data_source`、`group_by_fields` |
| 任意 `ab_*` | 非 AB | 删除 `ab_content`，标记破坏性风险 |

目标类型字段通过 `TypeSpecificFieldGenerator` 初始化，迁移代码不得复制语义关键词判断。

### 9.10 破坏性保护

以下行为属于破坏性修改：

- 删除非空 `children`。
- 删除 `local_context`。
- 删除 `iter_local_context`。
- 删除或覆盖 `data_source`。
- 删除 `ab_content`。
- 覆盖非空 `data_expression`。
- 容器迁移为 leaf。
- AB 类型迁移为非 AB 类型。

允许破坏性修改必须同时满足：

```text
ModifyNodeOperationInput.allow_destructive == True
NodeModifyPlan.destructive_authorized == True
```

任一条件不满足均返回：

```text
DESTRUCTIVE_CHANGE_NOT_ALLOWED
```

允许执行时，`migration_report` 至少记录：

```text
source_tree_node_type
target_tree_node_type
preserved_fields
initialized_fields
dropped_fields
children_action
original_children_count
destructive_risk
```

### 9.11 Modify Patch

所有成功修改统一使用整节点 replace patch：

```json
[
  {
    "op": "replace",
    "path": "/mapping_content/children/0",
    "value": {"tree_node_type": "simple_leaf"}
  }
]
```

类型迁移不生成多个局部 patch，避免旧类型字段残留。

### 9.12 Modify 错误码

| 错误码 | 含义 |
|---|---|
| `INVALID_NODE_PATH` | 路径语法不支持或匹配不唯一 |
| `TARGET_NODE_NOT_FOUND` | 目标节点不存在或不是节点对象 |
| `MODIFY_INTENT_ROUTE_FAILED` | 修改意图 LLM 调用或输出校验失败 |
| `MODIFY_PLAN_GENERATION_FAILED` | 修改计划 LLM 调用或输出校验失败 |
| `UNSUPPORTED_FIELD_UPDATE` | 字段不在允许集合或缺少必要 adapter |
| `UNSUPPORTED_TYPE_MIGRATION` | 源/目标类型或初始化能力不支持 |
| `DESTRUCTIVE_CHANGE_NOT_ALLOWED` | 未同时获得双重破坏性授权 |
| `NODE_SCHEMA_VALIDATION_FAILED` | 最终节点 Pydantic 校验失败 |
| `EXPRESSION_GENERATION_FAILED` | expression adapter 失败 |
| `DATATYPE_VALIDATION_FAILED` | datatype 配置非法 |
| `DATA_SOURCE_VALIDATION_FAILED` | data source adapter 或语义校验失败 |
| `AB_CONTENT_VALIDATION_FAILED` | AB content adapter 或内外类型校验失败 |

## 10. Prompt 契约

### 10.1 `node_type_route_prompt`

输入：

```text
query
```

输出：

```json
{
  "tree_node_type": "simple_leaf",
  "confidence": 0.95,
  "reason": "query describes a normal leaf field",
  "evidence_terms": ["账户ID", "字段"]
}
```

### 10.2 `common_node_field_prompt`

输入：

```text
query
```

输出：

```json
{
  "xml_name_property": {
    "xml_name": "ACCT_ID",
    "xml_format_type": "label",
    "xml_empty_field_type": "none"
  },
  "annotation": "账户ID节点",
  "reference_logic_area_id_list": []
}
```

### 10.3 `node_content_intent_prompt`

输入：

```text
query
tree_node_type
```

输出：

```json
{
  "tree_node_type": "simple_leaf",
  "data_type": "money",
  "requires_expression_generation": false,
  "requires_data_source_generation": false,
  "expression_query": null,
  "data_source_query": null,
  "ab_content_query": null,
  "reason": "金额字段"
}
```

### 10.4 `modify_intent_route_prompt`

输入：

```text
query
current_node_json
```

输出：

```json
{
  "intent_type": "change_node_type",
  "target_tree_node_type": "parent_list",
  "affected_fields": ["tree_node_type", "children", "data_source"],
  "requires_expression_generation": false,
  "requires_resource_selection": false,
  "destructive_risk": false,
  "reason": "用户要求改成列表节点"
}
```

### 10.5 `modify_plan_prompt`

输入：

```text
query
current_node_json
modify_intent_json
```

输出：

```json
{
  "intent": {
    "intent_type": "set_common_field",
    "target_tree_node_type": null,
    "affected_fields": ["xml_name_property.xml_name"]
  },
  "common_field_updates": {
    "xml_name_property": {
      "xml_name": "ACCT_ID"
    }
  },
  "type_field_updates": {},
  "expression_update_query": null,
  "datatype_update_query": null,
  "data_source_update_query": null,
  "ab_content_update_query": null,
  "migration_plan": null,
  "destructive_authorized": false,
  "rebuild_node": false
}
```

所有 prompt 必须明确：

- 仅输出严格 JSON object。
- 不输出 Markdown。
- 不输出最终节点。
- 不输出 patch。
- 不决定 `node_id`、`edsl_semi_struct`、`edsl_prompt`。

## 11. 校验顺序

### 11.1 Generate

```text
路径语法
-> 父节点存在性
-> 父节点容器能力
-> LLM route contract
-> LLM common field contract
-> LLM content intent contract
-> 类型专属字段完整性
-> TreeNodeTerm schema
-> patch 构造
```

### 11.2 Modify

```text
路径语法
-> 目标节点存在性
-> LLM intent contract
-> LLM plan contract
-> common/type update allowlist
-> 迁移策略或 adapter 执行
-> 破坏性双重授权
-> TreeNodeTerm schema
-> SemanticValidator
-> patch 构造
```

## 12. AB 节点要求

AB 节点必须满足：

```text
outer tree_node_type == ab_content.tree_node_type
```

`TreeNodeTerm.fill_ab_content_type` 可在输入缺少内部 discriminator 时补齐。序列化输出必须显式包含内部 `tree_node_type`，保证 patch value 可独立反序列化。

## 13. 失败结果不变量

### 13.1 Generate 失败

```text
success == False
generated_node is None
patch is None
failure_reason is not None
validation_errors 非空或具有明确失败原因
```

### 13.2 Modify 失败

```text
success == False
modified_node is None
patch_list == []
failure_reason is not None
```

若 Modify 已成功解析目标路径，可以返回 `original_node` 供调用方诊断，但不得返回候选半成品。

## 14. 测试与验收

### 14.1 Generate 单元测试

至少覆盖：

1. 五种允许生成的节点类型。
2. 公共字段 LLM 输出校验。
3. simple leaf 的三种 datatype。
4. parent、parent_list 默认字段。
5. pivot、two-level AB 类型一致性。
6. 叶子节点不能作为父容器。
7. 无效 JSONPath。
8. LLM 调用异常。
9. LLM 非法 JSON 或非法枚举。
10. 无关键词回退。
11. 失败结果不含 patch。

### 14.2 Modify 单元测试

至少覆盖：

1. 公共字段修改。
2. expression adapter 修改。
3. money/time/string datatype 修改。
4. parent 与 parent_list 双向迁移。
5. simple leaf 转 parent、parent_list、pivot、two-level。
6. pivot 与 two-level 双向迁移。
7. AB 转非 AB。
8. children 存在时容器转 leaf 的拒绝路径。
9. 双重授权后的破坏性成功路径。
10. `node_id` 默认保留及显式 rebuild 更新。
11. plan 字段白名单。
12. LLM 调用异常或非法输出。
13. 无关键词回退。
14. 失败结果不含 patch。

### 14.3 端到端测试

- 实际应用 Generate add patch，确认新节点追加到目标 `children`。
- 实际应用 Modify replace patch，确认目标节点被替换。
- patch 应用后的节点可以被 `TreeNodeTerm.model_validate()` 反序列化。
- Generate 与 Modify 的全量测试同时通过。
- 原 expression generator、resource manager、planner 测试不回归。

### 14.4 测试隔离

生产默认路径调用真实 `generate_by_llm()`；单元测试必须注入 deterministic fake gateway，禁止依赖网络或真实 API key。fake gateway 只模拟已约定的 JSON contract，不构成生产回退。

## 15. 扩展点

### 15.1 Adapter

可以扩展：

- expression adapter
- data-source adapter
- AB-content adapter
- context-update adapter

adapter 输出仍需通过对应 Pydantic 模型和最终 `TreeNodeTerm` 校验。

### 15.2 新节点类型

新增类型时必须同步更新：

1. `TreeNodeTerm.Config.allowed_fields_per_type`
2. `TreeNodeTerm.Config.special_configs`
3. 路由/意图 Pydantic Literal
4. prompt allowlist
5. `TypeSpecificFieldGenerator`
6. `MigrationPlanner`
7. `SemanticValidator`
8. 测试矩阵

### 15.3 Structured Output

未来可以把 prompt JSON contract 升级为模型服务原生 structured output，但不能改变本文定义的职责边界。

## 16. 当前限制

- JSONPath 仅支持简单字段和数字索引。
- LLM 语义阶段失败时不自动重试。
- 无 LLM 本地语义回退。
- 复杂 data source 和 AB content 原地编辑依赖 adapter。
- `ab_single_mapping_table` 可以存在于模型及修改目标类型集合中，但 Generate 默认不生成该类型，且迁移初始化能力必须显式提供后才能开放。
- Pydantic class-based `Config` 当前存在弃用警告，迁移到 Pydantic v3 前需要改造为兼容的新配置方式。

## 17. 完成定义

以下条件全部满足时，本规格实现完成：

1. Generate 和 Modify 的生产语义解释均通过 LLM 完成。
2. 生产节点语义关键词表和 query 提取正则已删除。
3. 五个 prompt 均可通过 prompt manager 渲染。
4. 所有 LLM 输出都经过 Pydantic contract 校验。
5. 所有最终节点都经过 `TreeNodeTerm.model_validate()`。
6. 类型迁移遵守迁移矩阵。
7. 破坏性修改遵守双重授权。
8. 失败结果不含可应用 patch。
9. 端到端 patch 可应用且节点可反序列化。
10. 项目全量测试通过。
