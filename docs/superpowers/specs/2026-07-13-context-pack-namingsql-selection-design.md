# ContextPack 驱动的 NamingSQL 选择设计

## 状态与决策

本设计于 2026-07-13 经讨论确认。它修正 `2026-07-10-context-pack-manager-design.md` 中“将 NamingSQL 作为普通 Provider 并入 ContextPack”的目标态：NamingSQL 选择需要综合多个 ContextPack section，因此属于 ContextPack 之后的受约束决策，不是独立上下文召回源。

## 目标

- `ContextPackManager` 只召回当前任务需要的事实、规范和参考范例。
- `NamingSqlSelector` 显式接收 `ContextPack` 与权威 `LoadedResource`，据此选择有界 NamingSQL Top-K。
- 复用现有 NamingSQL 混合召回、LLM reranker/organizer、参数约束和 planner 防越界能力。
- embedding 或 LLM 不可用、失败或输出非法时，降级到稳定的确定性 Top-K，而不是丢失整个 ContextPack。
- 迁移完成后移除专用 NamingSQL Context Manager 的跨资源编排职责；保留可复用的底层索引、检索和严格校验组件。

## 非目标

- 不把 `ContextPackManager` 扩展成支持 Provider 依赖图的通用工作流引擎。
- 不允许 LLM 创建或修改 NamingSQL ID、所属 BO、参数、返回类型或绑定。
- 不在 ContextPack 内加入 `namingsql` section，也不使用 ContextPack 的 authority/conflict 机制表达选择结果。
- 不改变 planner 只能使用已批准候选的约束。

## 两层架构

```text
ContextPackRequest(node, query, resource_names)
  -> ContextPackManager
       -> current_tree / dev_skill / ootb_edsl
  -> ContextPack
  -> NamingSqlSelectionRequest(context_pack, loaded_resource, selection hints)
  -> NamingSqlSelector
       -> canonical NamingSQL candidate construction
       -> hard constraints and deterministic hybrid recall
       -> optional LLM rerank / organize
       -> canonical revalidation
  -> NamingSqlSelection
  -> typed context / planner / validator
```

第一层回答“当前任务有哪些相关上下文”。第二层回答“在这些上下文和权威注册表约束下允许使用哪些 NamingSQL”。后者是派生决策，不回写或改变输入 ContextPack。

## 契约

`ContextPackRequest.resource_names` 不再接受 `namingsql`。阶段一为迁移预留的枚举值和未注册错误在兼容窗口内可以保留，但公开文档、工厂和新调用方不得再申请它；最终在确认无消费者后删除。

`NamingSqlSelectRequest` 在迁移期保留现有站点、项目、节点路径、BO hint、logic-area IDs、Top-K 和 debug 字段，并新增必填 `context_pack: ContextPack`。Selector 不再自行召回当前树、开发规范或 OOTB 范例。

`NamingSqlSelectResponse` 继续作为独立选择结果，包含：

- canonical、按最终优先级排序的候选；
- 从 ContextPack 派生的需求提示与选择约束；
- 确定性召回、LLM 精选、降级和 canonical 复验的 evidence trace；
- `selection_mode = llm | deterministic_fallback`；
- 非致命降级 warnings；
- 仅在没有任何合法候选或权威输入无效时返回失败。

## ContextPack 消费规则

Selector 通过独立的 `NamingSqlContextAdapter` 读取 pack，避免让现有检索器依赖通用 pack 模型细节：

- `current_tree` 提供实际节点、字段、local/iter 可见性和结构事实；
- `dev_skill` 提供领域取值规则、空值处理和组合规范；
- `ootb_edsl` 仅提供参考实现信号，不得覆盖当前树或注册表事实；
- pack 的 warning、conflict、status 和被裁剪证据会进入选择 trace；
- `failed` pack 不进行选择；`partial` pack 可以选择，但必须记录缺失 section；
- Selector 只消费 pack 中实际存在的 section，不回看完整当前树或开发 skill 文件。

适配器输出有界、稳定序列化的 `NamingSqlSelectionContext`，供确定性召回和 LLM prompt 共用，避免两条路径理解不同上下文。

## 候选召回与 LLM 精选

候选只从当前请求的 `LoadedResource` NamingSQL registry 构造。先应用 BO、ID、参数可绑定性、返回类型和显式引用等硬约束，再组合精确、词法与 embedding 召回，形成有界候选集。

LLM 只接收 opaque candidate ID、canonical 摘要和有界 `NamingSqlSelectionContext`。输出只能包含给定候选 ID，不能重复、超过 Top-K 或改变候选内容。Organizer 的顺序是 LLM 模式下的最终顺序；每个输出 ID 随后重新映射到 `LoadedResource` 并严格复验。

以下情况统一降级到 LLM 前的确定性顺序：

- LLM/embedding 未配置或不可用；
- transport、解析或 schema 校验失败；
- 返回未知、重复或过量 ID；
- canonical 回读不一致。

降级不将选择标记为失败；响应使用 `deterministic_fallback`、稳定 warning code 和 evidence trace。只有权威 registry 不可用、请求/pack 无效或硬过滤后零候选时才失败。

## 调用链迁移

`ValueLogicGenerator` 在需要 NamingSQL 的路由中：

1. 使用显式资源白名单构建 ContextPack；
2. 将该 pack 和本次请求的 `LoadedResource` 传给 request-scoped Selector；
3. 将选择结果交给 typed-context builder 与 planner；
4. 保持 planner prompt 只暴露批准的 Top-K；
5. 保持本地 validator 拒绝 Top-K 外的 NamingSQL。

非 NamingSQL 路由仍可构建所需 ContextPack，但不得创建或调用 Selector。迁移期兼容 facade 可以继续返回 `NamingSqlSelectResponse`，内部不再调用旧的 `ContextManager.build_context`。

## 失败语义

- ContextPack 请求无效或 `status=failed`：选择失败，使用稳定公开错误码。
- ContextPack 为 `partial`：继续选择，将缺失资源作为 warning/trace。
- LLM/embedding 失败或非法：确定性降级，选择仍可成功。
- `LoadedResource` 缺失、canonical 候选无法重建或硬过滤后无候选：选择失败。
- 未知内部异常继续抛出，不把私密异常文本暴露给公开响应。

## 测试策略

- 契约测试：请求必须携带 ContextPack，响应严格校验选择模式、warnings 和成功/失败组合。
- 适配器测试：各 section、partial/failed、conflict、裁剪和 authority 信号稳定映射且有预算边界。
- 召回测试：只有 `LoadedResource` 候选可返回，硬约束先于相关性，输入不被修改。
- LLM 测试：合法顺序被接受；未知、重复、过量、异常和未配置均回退确定性 Top-K。
- 集成测试：Selector 确实使用 pack 中的 skill/current-tree 信号，且不自行重新召回上下文。
- 调用链测试：NamingSQL 路由按 ContextPack -> Selector -> typed context -> planner 执行；非 NamingSQL 路由零 Selector 调用。
- 防越界测试：planner 和本地 validator 均不能使用 Top-K 外候选。
- 回归测试：阶段一 ContextPack、现有 NamingSQL、planner、typed-context 和全量测试保持通过。

## 完成标准

1. NamingSQL 不作为 ContextPack Provider 注册或请求。
2. Selector 的选择输入显式包含 ContextPack 和 request-scoped `LoadedResource`。
3. 所有输出候选均可严格映射回权威 registry。
4. LLM 只精选有界候选，失败时稳定降级且不使可用选择失败。
5. Planner 只看到并只能使用获批 Top-K。
6. 旧专用 Context Manager 不再承担 NamingSQL 跨资源召回编排。
7. 相同 ContextPack、registry snapshot 和请求在无 LLM 时产生相同结果。
