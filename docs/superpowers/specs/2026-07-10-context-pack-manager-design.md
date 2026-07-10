# ContextPackManager 统一上下文管理设计

## 状态

本设计于 2026-07-10 经讨论确认。本文只定义目标架构、契约、召回规则和迁移路径，不授权实现。

## 背景与问题

仓库当前的上下文能力分散在 NamingSQL 专用 Context Manager、资源过滤器和 `tree_reference_resolver` skill 中。它们已经具备资源建模、树索引、本地 embedding、词法召回和 canonical 校验等能力，但入口、失败语义和输出契约各不相同。

新系统需要仿照 Claude Code 和 Codex 的按需上下文获取方式，在本地构建唯一的上下文管理入口。调用方必须显式声明允许搜索的资源，管理器仅调用白名单中的资源 Provider，并返回统一的结构化 `ContextPack`。首期资源是工程开发知识、OOTB 基线 EDSL 和当前 EDSL 树；目标态还必须完整整合 NamingSQL 上下文选取，最终删除专用 NamingSQL Context Manager。

## 目标

- 以 `ContextPackManager` 作为仓库唯一上下文管理入口。
- 公开输入只包含当前操作节点、查询和资源类型白名单。
- 返回统一、结构化、可追溯和有预算边界的 `ContextPack`。
- 只调用 `resource_names` 明确列出的 Provider。
- 从自然语言 Markdown 开发 skill 中召回领域取值配方。
- 从 OOTB 基线 EDSL 中召回相关节点或有界子树范例。
- 按需搜索当前 EDSL 中实际存在的节点、字段及对当前节点可见的 local/iter 变量。
- 将 NamingSQL 作为标准资源 Provider 迁入统一管理器。
- 采用本地优先召回；embedding 或 LLM 不可用时仍能返回确定性结果。
- 所有返回项都能映射回 canonical 本地来源，并记录召回、冲突和裁剪证据。

## 非目标

- 不由 `ContextPackManager` 生成最终 prompt。
- 不允许 Provider 或开发 skill 绕过资源白名单读取任意工程文件。
- 不把开发 skill 设计成可执行脚本或自治 agent。
- 不在首期引入外部向量数据库。
- 不把不同资源的相关性分数合并成一个跨资源总排名。
- 不在本设计阶段实现代码或立即删除现有 NamingSQL 链路。

## 核心术语

- **ContextPackManager**：唯一上下文编排入口，负责白名单门控、Provider 调度、统一校验、预算和组装。
- **ContextPack**：管理器的唯一公开输出；包含当前节点、资源 sections、证据、冲突、告警和 trace。
- **ProjectContext**：request-scoped 工程快照，注入当前树、OOTB 基线、开发 skill 路径和 `LoadedResource`。它不是公开请求的一部分。
- **Provider**：针对一种资源构建候选、执行召回并返回 canonical `ContextItem` 的组件。
- **DevSkillInvoker**：静态开发知识定位器。它定位和读取 Markdown 配方，但不执行 Markdown 中描述的动作。
- **LocalResourceSearchTool**：受 Source Registry 约束的本地搜索工具；它不接受任意文件路径。

## 目标架构

```text
业务调用链
  -> ContextPackRequest(node, query, resource_names)
  -> ContextPackManager
       -> ResourceGate
       -> SourceRegistry
       -> requested Providers only
       -> validation / conflict detection / budget
  -> ContextPack
  -> chain-specific ContextPackRenderer
  -> prompt / planner
```

组件职责：

- `ResourceGate` 校验白名单，拒绝未知资源名，并保证未申请的 Provider 零调用。
- `SourceRegistry` 将稳定资源名映射到 Provider 和内部 `RecallProfile`。
- Provider 独立完成本资源的候选生成、过滤、召回、重排和 canonical 校验。
- `ContextPackBuilder` 做跨资源去重、冲突检测、分源预算、全局预算和状态汇总。
- 各业务链自己的 `ContextPackRenderer` 将结构化 pack 转为 prompt；renderer 不得改变事实来源的 authority。

新系统复用现有 `LoadedResource`、本地 BGE-M3 adapter、树索引思想和 `ContextAsset` 的来源/证据原则，但不继承 NamingSQL 专用 assembler、固定 resolver 顺序、必须调用 LLM 的 fail-closed 语义和专用输出模型。

## 公开请求契约

```python
class ContextPackRequest(BaseModel):
    node: dict[str, Any]
    query: str
    resource_names: list[Literal[
        "dev_skill",
        "ootb_edsl",
        "current_tree",
        "namingsql",
    ]]
```

契约规则：

- `node` 是当前操作节点，不是整棵 EDSL 树。
- `query` 是当前用户意图或任务描述。
- `resource_names` 是严格白名单，不是提示，也不携带优先级。
- 列表去重后为空、出现未知资源名、`node` 为空或 `query` 为空均属于无效请求。
- 完整当前树、OOTB、开发 skill 和注册表由 `ProjectContext` 注入，避免每次请求复制大对象。
- 仅当申请 `current_tree` 时，Provider 才定位并索引完整当前树。该资源需要 `node` 中存在可映射回当前树的稳定标识或路径。
- 预算和 top-k 不增加为必填公开字段；由可注入的 `RecallProfile` 管理。

## ContextPack 契约

```python
class ContextPack(BaseModel):
    status: Literal["complete", "partial", "failed"]
    request_summary: dict[str, Any]
    current_node: dict[str, Any]
    sections: list[ContextSection]
    conflicts: list[ContextConflict]
    warnings: list[ContextWarning]
    trace: list[ContextTraceItem]


class ContextSection(BaseModel):
    resource_name: ResourceName
    status: Literal["ready", "empty", "unavailable", "degraded", "error"]
    items: list[ContextItem]
    evidence: list[RetrievalEvidence]
    budget_usage: BudgetUsage
    metadata: dict[str, Any]


class ContextItem(BaseModel):
    item_id: str
    resource_name: ResourceName
    item_type: str
    authority: Literal["authoritative", "normative", "reference"]
    content: dict[str, Any]
    summary: str
    locator: SourceLocator
    evidence: list[RetrievalEvidence]
    content_hash: str
```

`summary` 是供模型快速阅读的受控摘要，不能替代 `content` 和 canonical locator。Provider 可以在 section `metadata` 中保留资源特有的结构，例如 NamingSQL 允许的候选 ID、参数约束和上下文需求。

输出 section 使用稳定注册顺序：

```text
current_tree -> namingsql -> dev_skill -> ootb_edsl
```

这个顺序只用于确定性序列化，不表达覆盖关系。覆盖关系由 `authority` 和冲突规则决定。

## Provider 设计

### DevSkillProvider

开发 skill 是工程内由开发人员用自然语言 Markdown 维护的领域配方库。例如“客户姓名”配方描述 title、姓、中间名和名的取值、判空及拼接方式。

`DevSkillInvoker` 的内部链路：

```text
query + node
  -> SkillCatalog
  -> MarkdownSkillParser
  -> LocalResourceSearchTool.search
  -> CanonicalReader.read_slice
  -> ContextItem
```

规则：

- 初始版本只读取 `ProjectContext` 配置的一个开发 skill 文件；注册表模型允许未来增加更多文件。
- 使用 Markdown AST，而不是正则表达式，按 H2/H3 叶子标题形成知识条目。
- 条目继承必要的父标题语境；同一配方下的规则、约束和示例保持为一个逻辑单元。
- 只有超长条目才进行有重叠的二级分块。
- 稳定 ID 由 `source_id + heading_path` 生成；内容 hash 用于版本与回读校验。
- 召回顺序为稳定 ID/别名精确命中、关键词/BM25、本地 embedding、可选 LLM 重排。
- 默认返回 1 至 3 条配方，authority 为 `normative`。
- skill 内容只能提供取值规范，不能虚构当前树或资源注册表中不存在的字段和参数。

### OotbEdslProvider

OOTB 是一个基线 EDSL 工程，作为相似实现范例，而不是当前工程事实。

规则：

- 索引单位是 EDSL 节点；返回单位是相关节点或有界子树片段。
- 每个返回项包含祖先路径、节点类型、关键配置、必要的有限深度子树和匹配证据。
- 先按兼容节点类型、数据类型和结构特征做硬过滤，再使用名称/注释、半结构语义、结构特征、embedding 和可选 LLM 重排。
- 默认返回 1 至 3 个范例，authority 为 `reference`。
- OOTB 项不能覆盖当前树事实或开发 skill 规范；冲突时降级或裁剪，并记录原因。

### CurrentTreeProvider

该 Provider 只关心当前 EDSL 中实际存在的节点、字段及 local/iter 变量，不包含 BO 字段。

规则：

- 仅当白名单包含 `current_tree` 时才建立或查询当前树索引。
- 候选单位包括 EDSL 节点、`simple_leaf` 字段、表格 detail/group/summary 字段，以及 local/iter 变量。
- local/iter 候选必须对当前操作节点可见。
- 所有结果必须映射回当前树中的 canonical node ID、JSONPath 或 XMLPath。
- 召回顺序为显式名称/路径、可见范围与结构邻近、关键词、embedding 和可选 LLM 重排。
- 默认返回 3 至 10 项，authority 为 `authoritative`。
- BO registry 字段不混入此 Provider；如果未来需要，应注册独立资源类型。

### NamingSqlProvider

NamingSQL 在目标态是标准 Provider，不再返回独立 `NamingSqlSelectResponse`。

规则：

- 候选只能来自权威 `LoadedResource` NamingSQL registry。
- 每个 item 保留 canonical NamingSQL ID、BO、名称、用途、参数、返回类型、必要 BO 事实和检索证据。
- 使用 BO/ID/参数的精确补召回、本地 embedding、词法召回和可选 LLM 重排。
- 模型不能创建候选、参数或资源事实；无效重排输出被丢弃并回退到重排前的 canonical 顺序。
- 默认返回 Top-K 5，authority 为 `authoritative`。
- section metadata 保留允许使用的候选 ID、参数约束和上下文需求。Planner 只能使用 pack 内候选。

## 共用召回协议

每个 Provider 遵循相同阶段协议：

```text
1. 白名单门控
2. 资源特有硬约束过滤
3. 精确、词法和结构召回
4. 本地 embedding 召回
5. 可选 LLM 重排
6. canonical 校验与原文回读
```

具体规则：

- 精确 ID、名称和路径命中固定置顶。
- 词法和 embedding 结果只在同一 Provider 的同类候选中使用稳定 rank fusion 合并。
- 不跨资源比较相关性分数。
- LLM 只对已提供的 opaque aliases 排序，不能返回未知 ID。
- LLM 或 embedding 不可用时使用前一确定性阶段的结果，并将 section 标为 `degraded`。
- 无效可选重排不导致整包失败；系统丢弃该重排结果并记录 warning。
- 每个 item 都必须携带来源、召回动作、匹配理由、locator 和 content hash。

## 文件检索工具

`LocalResourceSearchTool` 是 Provider 内部工具，不直接暴露任意文件系统访问：

```python
search(
    source_id: str,
    query: str,
    filters: SearchFilters,
    limit: int,
) -> list[SearchHit]

read_slice(
    locator: SourceLocator,
    expected_hash: str,
) -> CanonicalSlice
```

安全与一致性规则：

- `source_id` 必须存在于 Source Registry。
- locator 必须位于已注册资源根内，不能使用调用方传入的任意路径。
- `SearchHit` 中的索引文本只用于定位；进入 `ContextPack` 的内容必须通过 `read_slice` 回读 canonical 源。
- hash 不匹配说明索引已过期，必须使缓存失效并重建，不能返回旧内容。
- 文件大小、Markdown 深度、单条字符数、EDSL 节点数和返回项数均有配置边界。

## 索引生命周期

- `dev_skill`：开发 skill 内容 hash 变化时重建。
- `ootb_edsl`：基线工程版本或内容 hash 变化时重建。
- `current_tree`：按当前树 snapshot/version 懒构建，仅白名单请求触发。
- `namingsql`：`LoadedResource` registry fingerprint 变化时重建。

首期使用进程内 LRU 索引缓存。embedding 向量可按内容 hash 使用本地持久缓存，但不引入外部向量数据库。缓存键必须包含 source ID、source version、解析器版本和 embedding 模型版本。

## Authority 与冲突处理

来源分为三个 authority：

| Authority | 来源 | 决策范围 |
| --- | --- | --- |
| `authoritative` | 当前节点、current tree、NamingSQL registry | 决定存在性、路径、类型、可见范围、参数和资源事实 |
| `normative` | 开发 skill | 决定领域内应该如何取值、组合、判空和生成 |
| `reference` | OOTB EDSL | 提供类似实现范例 |

冲突规则：

- 当前树路径、字段类型、local/iter 可见性和 NamingSQL 参数以权威源为准。
- 开发 skill 与当前事实不兼容时，两者都保留并生成结构化 `ContextConflict`；系统不得静默使用 OOTB 替代。
- OOTB 与权威事实或开发规范冲突时，OOTB 项降级或在预算阶段优先裁剪。
- 同级资源不做隐式覆盖；按稳定 ID 去重，无法合并的冲突项并列并保留来源。

## ContextPack 组装与预算

`ContextPackBuilder` 使用稳定流程：

```text
1. 保留当前操作节点
2. 校验 Provider item 的 canonical ID、locator 和 hash
3. 按稳定 ID 去重并执行 authority-aware 冲突检测
4. 应用各 Provider 的 item/字符预算
5. 应用 ContextPack 全局预算
6. 汇总 status、sections、conflicts、warnings 和 trace
```

预算由内部 `RecallProfile` 配置，公开请求不增加预算字段。裁剪优先级：

1. 当前操作节点不可裁剪。
2. 显式 ID/名称/路径硬命中优先保留。
3. 权威事实优先于规范，规范优先于参考范例。
4. 同一 authority 内按 Provider 的稳定排序裁剪。
5. 每次裁剪都写入 section evidence 和全局 trace。

## 状态与失败语义

整包状态：

- `complete`：所有请求 Provider 正常完成。
- `partial`：至少一个 Provider 为 `empty`、`unavailable`、`degraded` 或 `error`，但仍有可用内容。
- `failed`：请求本身无效、`ProjectContext` 不可用，或所有请求 Provider 都无法提供可用内容。

整包失败条件：

- `node` 或 `query` 为空。
- `resource_names` 为空或包含未知资源名。
- `ProjectContext` 无法建立。

局部问题：

- 请求的 skill、OOTB、当前树或 registry 缺失。
- 当前节点无法映射到请求的 current tree snapshot。
- 某 Provider 解析失败或没有候选。
- embedding 或 LLM 不可用。
- 可选重排输出无效。
- 预算导致候选裁剪。

局部问题不会抹掉其他已验证 section。即使 pack 为 `partial` 或 `failed`，也返回已验证 items、warnings 和 trace，供调用方决定是否继续。

## 业务调用链适配

- node generation 和 modification 显式申请所需的 `dev_skill`、`ootb_edsl`、`current_tree`。
- expression generation 通常申请 `dev_skill` 和 `current_tree`；确实需要数据访问时再加入 `namingsql`。
- NamingSQL selection 在迁移期由 selector 构造统一请求，并从 `namingsql` section 读取候选。
- 各链的 renderer 只消费申请到的 sections；它不能回看完整注册表或自行搜索资源。
- 未列入 `resource_names` 的 Provider 必须零调用，不能因模型判断而自动增加资源。

## NamingSQL 迁移路径

### 阶段一：建立统一核心

- 实现 `ContextPackManager`、公开请求/响应契约、Source Registry 和 Pack Builder。
- 实现 `dev_skill`、`ootb_edsl` 和 `current_tree` Provider。
- 保持现有 NamingSQL 专用链不变。

### 阶段二：接入 NamingSQL

- 实现 `NamingSqlProvider`，复用现有权威资源 builder、retrieval 和 canonical 校验能力。
- 旧 `NamingSqlSelector` 通过适配器消费 `ContextPack`。
- 在测试或 debug 环境进行旧链与新 Provider 的 shadow 对比，重点验证候选边界、参数约束和 Planner 防越界能力。

### 阶段三：完成统一

- 将所有调用方切换到 `ContextPackManager`。
- 删除专用 NamingSQL Context Manager、重复的请求/响应模型和重复检索编排。
- 保留必要的 NamingSQL 领域模型作为 Provider item content，而不是独立上下文系统。

## 测试策略

### 契约与单元测试

- 公开请求只接受三个字段并严格校验资源白名单。
- 未申请 Provider 零调用。
- Markdown AST 正确保留标题层级、规则、约束、示例和代码块。
- heading locator、content hash 和 canonical 回读一致。
- CurrentTreeProvider 只返回实际节点、字段和可见 local/iter。
- OOTB 子树有深度、节点数和字符边界。
- 精确命中固定置顶；rank fusion 只在单一 Provider 内发生。
- embedding/LLM 失败时使用确定性结果并标记 degraded。
- authority 冲突、稳定去重和预算裁剪符合规则。
- 所有缓存按 source/version/parser/model 变化正确失效。

### 集成测试

- 不含 `current_tree` 的请求不扫描完整当前树。
- 不含 `ootb_edsl` 的请求不加载或查询 OOTB。
- 缺失单一资源返回 partial，而不是丢失其他 section。
- Dev skill 回读内容来自 canonical Markdown，而不是索引摘要。
- NamingSQL item 全部映射到 `LoadedResource`，参数和 BO 事实未被模型改写。
- Planner 无法使用 ContextPack 之外的 NamingSQL。
- 相同 snapshot、query、白名单在无 LLM 时产生稳定输出。

### 端到端场景

- 查询“生成客户姓名”时，`dev_skill` 召回 title、姓、中间名、名、判空和拼接配方。
- 同时申请 `current_tree` 时，只返回当前 EDSL 中实际存在且可见的对应字段或变量。
- 同时申请 `ootb_edsl` 时，返回相似客户姓名实现范例，但范例不能覆盖开发规范和当前树事实。
- NamingSQL 迁移后，选择链只消费 `namingsql` section，并继续满足 Top-K 和参数约束。

## 完成标准

1. 仓库对外只有一个 `ContextPackManager` 上下文入口。
2. 公开调用输入为 `node`、`query` 和 `resource_names`，输出为 `ContextPack`。
3. 未列入白名单的 Provider 零调用。
4. 每个 ContextItem 都可追溯到 canonical 本地来源并带 evidence。
5. 开发 skill 可由开发人员继续使用自然语言 Markdown 维护。
6. 当前树只暴露实际节点、字段和对当前节点可见的 local/iter。
7. OOTB 返回有界范例，不覆盖权威事实或开发规范。
8. embedding 和 LLM 不可用时仍产生稳定的确定性 ContextPack。
9. NamingSQL 完成三阶段迁移，Planner 无法使用 pack 外候选。
10. 专用 NamingSQL Context Manager 和重复上下文模型被移除。
