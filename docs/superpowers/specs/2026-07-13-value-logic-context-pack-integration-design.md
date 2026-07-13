# ValueLogicGenerator ContextPack 集成设计

## 状态

本设计于 2026-07-13 经讨论确认。它将 ContextPack 提升为 `ValueLogicGenerator` 每次请求的前置共享上下文，并使用一次轻量 LLM 布尔路由决定是否搜索当前树。

## 目标

- 请求进入 `ValueLogicGenerator` 后、spec 生成前构建一次 ContextPack。
- `dev_skill` 与 `ootb_edsl` 固定召回。
- 轻量 LLM 只判断是否追加 `current_tree`。
- 路由失败时默认使用全部 ContextPack 资源。
- 将同一个 ContextPack 保存在 `GenerationContext` 中，向 spec、NamingSQL 选择、typed context 和 planner 显式传递。

## 非目标

- 不复用或扩展复杂的 difficulty/resource router。
- 不让路由器决定 Top-K、资源排序、NamingSQL、BO 或 function。
- 不让各下游阶段重复构建 ContextPack。
- 不把 ContextPack 塞入 `FilteredEnvironment`。
- 不向轻量路由器发送整棵 EDSL 树或完整资源注册表。

## 调用链

```text
ValueLogicRequest
  -> FastContextResourceRouter
       fixed: dev_skill + ootb_edsl
       boolean: use_current_tree
       failure: all resources
  -> ContextPackManager.build (exactly once)
  -> GenerationContext.context_pack
       -> ExpressionSpecGenerator
       -> NamingSqlSelector
       -> TypedExpressionContextBuilder
       -> LLMPlanner / SimpleExpressionPlanner
```

ContextPack 是本次生成请求的不可变上下文快照。所有下游阶段接收同一个对象，不重新召回、不追加 section，也不修改 pack。

## 轻量资源路由

新增独立 `FastContextResourceRouter`，不依赖 `LLMDifficultyRouter`。公开结果是一个冻结数据对象：

```python
@dataclass(frozen=True, slots=True)
class ContextResourceRoute:
    use_current_tree: bool
    fallback: bool = False
```

路由器输入只有：

- 用户 query；
- 当前节点的 `node_id`、name、type、annotation；
- parent 节点存在时的同类有界摘要。

LLM 只返回严格 JSON：

```json
{"use_current_tree": true}
```

路由器不请求解释，不执行重试或修复调用。只有响应是对象且 `use_current_tree` 是严格布尔值时才接受结果。

以下情况直接返回 `use_current_tree=True, fallback=True`：

- LLM 未配置或不可用；
- 调用异常或超时；
- 响应不是 JSON 对象；
- 字段缺失；
- 字段值不是严格布尔值。

因此失败时的 ContextPack 白名单固定为全量资源：

```text
dev_skill + ootb_edsl + current_tree
```

成功且 `use_current_tree=False` 时只使用固定资源：

```text
dev_skill + ootb_edsl
```

路由 fallback 不阻断请求。调用链记录稳定诊断码 `CONTEXT_RESOURCE_ROUTE_FALLBACK`，不得暴露底层异常文本。

## ContextPack 构建

`ValueLogicGenerator.generate()` 在创建完整 `GenerationContext` 前调用路由器并构造 `ContextPackRequest`。`ProjectContext` 使用本次请求的：

- 当前 EDSL tree；
- 配置的完整 OOTB tree；
- 配置的 dev-skill Markdown 路径；
- request-scoped `LoadedResource`。

ContextPack 每个请求最多构建一次。非 NamingSQL 路由同样构建。`partial` 或 `failed` pack 仍向下传递，由下游使用现有输入降级；ContextPack 的状态、warnings 和 trace 保留可观测性。

路由 fallback 诊断通过不可变复制追加到 pack warning/trace，或保存在 `GenerationContext` 的独立诊断字段；不得修改 Manager 内部缓存或 Provider 输出。

## GenerationContext 与下游契约

`GenerationContext` 新增：

```python
context_pack: ContextPack
```

下游签名调整：

- `ExpressionSpecGenerator.generate(..., context_pack=ctx.context_pack)`；
- `NamingSqlSelectRequest(context_pack=ctx.context_pack, ...)`；
- `TypedExpressionContextBuildInput(..., context_pack=ctx.context_pack)`；
- `LLMPlanner.plan(..., context_pack=ctx.context_pack)`；
- `SimpleExpressionPlanner.plan(..., context_pack=ctx.context_pack)`。

自定义/旧注入实现迁移到新显式关键字参数。生产代码不通过反射吞掉参数，也不在不同阶段重新构造等价 pack。

## Prompt 与预算

新增通用 `ContextPackPromptRenderer`，只渲染：

- pack status；
- section resource/status；
- 每个 item 的 ID、authority、summary、结构化 facts；
- warnings/conflicts 的稳定码和键；
-必要的裁剪 trace。

不渲染完整树、未召回注册表、任意文件内容或 SQL 正文。renderer 有独立字符和 item 预算，输出采用稳定 JSON，供 spec prompt 与 plan prompt 复用。

NamingSQL Selector 继续使用现有 `NamingSqlContextAdapter` 消费完整结构化 pack，不从 prompt JSON 反解析。

## 测试策略

- 路由器严格接受布尔输出。
- 未配置、异常、超时语义、非对象、缺字段和非布尔值全部回退全量资源。
- `dev_skill` 与 `ootb_edsl` 始终请求。
- `use_current_tree=False` 时 CurrentTreeProvider 零调用。
- fallback 时 CurrentTreeProvider 被调用。
- ContextPack 在 spec 前构建且每次请求只构建一次。
- spec、Selector、typed-context 和 planner 收到同一个 pack 对象。
- 非 NamingSQL 路由不调用 Selector，但仍向 spec、typed-context 和 planner 传递 pack。
- prompt renderer 保持预算，不包含完整树、SQL 正文或未召回资源。
- 保持 ContextPack、NamingSQL、planner、typed-context 和全量回归测试通过。

## 完成标准

1. 每个 ValueLogic 请求首先完成轻量上下文资源判断。
2. dev-skill 与 OOTB 固定召回，current-tree 由单个严格布尔值控制。
3. 路由失败默认启用全部三类资源且不阻断请求。
4. ContextPack 每次请求只构建一次。
5. `GenerationContext` 持有 pack，所有指定下游阶段收到同一对象。
6. 下游 prompt 使用统一有界 renderer，不泄漏未召回或权威原始数据。
7. 工作区已有的 `tests/test_context_pack_ootb.py` 修改被完整保留。
