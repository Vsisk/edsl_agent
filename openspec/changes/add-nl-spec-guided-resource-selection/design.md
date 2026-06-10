## Context

当前生成链路在 `ValueLogicGenerator._generate_expression_by_plan()` 中先根据原始 query 做资源难度路由，再调用 `build_filtered_environment()` 完成候选召回、明确资源名称匹配、语义筛选和候选合并，最后把筛选结果传给 `LLMPlanner`。这条链路对显式资源名和较完整 query 效果较好，但当 SA 只写了“取账户余额”这类简单概念时，系统缺少术语库和区域经验库提供的业务取值经验，容易筛错资源或让 planner 自行补业务假设。

本次改造需要把 NL Spec 放在资源筛选之前。第一版输入明确为 `region_type + cbs_name + query + node + site_id + project_id`：`region_type` 来自上游 PDF 区域解析，用于取对应区域经验库；`cbs_name` 来自原始需求的 CBS 术语识别结果，用于取对应术语。现有 query 驱动资源筛选机制不废弃，而是被 `SpecResourceSelector` 包装并作为 fallback 保留。

## Goals / Non-Goals

**Goals:**

- 基于 `region_type + cbs_name` 生成可测试、可传递的 NL Spec，使用自然语言承载业务取值经验。
- 当 NL Spec 可用时，让资源类型、搜索空间、候选召回和语义筛选都受 `source_type + nl` 约束。
- 保留明确资源名称匹配、语义匹配、候选合并等现有能力，但让它们在 spec 约束下运行。
- 保证 planner 只能看到 `SpecResourceSelector` 产出的资源，不能绕过 spec 再使用未筛选资源。
- 在规格缺失、规格不可用或规格无法筛出有效资源时，稳定回退到现有 query 驱动筛选。

**Non-Goals:**

- 第一版不做本体推理、复杂概念识别或跨 CBS 概念扩展。
- 第一版不把 BO 入参规划成强结构化参数契约；BO 条件、返回字段等先放在 `value_source_candidates[].nl` 中表达。
- 第一版不替换现有资源注册表、关键词工具、LLM 语义筛选或 planner schema。
- 第一版不要求新增外部知识服务；术语库和经验库通过可注入 provider 接口接入即可。

## Decisions

### Decision 1: 新增 NL Spec 生成服务，而不是把经验直接拼入 query

引入 `NLSpecGenerator` 或等价服务，输入 `region_type`、`cbs_name`、`query`、`node_info`、`site_id`、`project_id`，输出结构化的 `NLSpec`。生成逻辑先查术语库和区域经验库，再调用 LLM 或本地组合逻辑生成固定 JSON 结构。

选择该方案的原因是 NL Spec 需要成为资源筛选和 planner 的共同契约，而不仅是一个更长的 prompt。直接把经验拼进 query 会让现有筛选逻辑难以判断哪些资源类型是约束、哪些只是提示词，也无法记录 evidence 和 fallback 原因。

替代方案是只修改 `resource_filter` prompt，让它读取术语和经验。这会把知识解析、资源约束、fallback 都塞进一个 LLM 调用，行为难以测试，因此不采用。

### Decision 2: 使用 `SpecResourceSelector` 包装现有筛选机制

新增 `SpecResourceSelector` 作为资源筛选入口。它先尝试生成并验证 NL Spec；若 spec 可用，则按 `value_source_candidates[].source_type` 映射资源组，按每条候选的 `nl` 构造受约束的检索 query，并调用现有候选召回、工具搜索、语义筛选和合并逻辑。若 spec 不可用或筛选结果为空，则调用当前 query 驱动路径。

这样可以保留已有资源筛选机制的回归资产，同时把搜索空间、资源类型和业务经验来源前移到 spec。现有 `build_filtered_environment()` 可以演进为支持 spec 参数，也可以由 selector 多次调用它并合并结果；实现时优先选择改动最小、测试最清晰的方式。

替代方案是重写一套 spec-only 检索器。它短期会绕开已有 keyword search、LLM rerank、候选合并和 fallback，风险更高，因此不采用。

### Decision 3: 以 `source_type + nl` 作为检索条件和约束来源

`value_source_candidates` 的 `source_type` 决定允许搜索的资源类型：`context` 只允许 global/local context；`bo_field` 和 `naming_sql` 允许 BO 及其字段、naming SQL；`function` 允许 function。每个候选的 `nl` 必须作为检索文本参与候选召回和 LLM 语义筛选，不允许只把完整 spec 当成普通提示词。

这样可以避免“spec 说要从上下文取值，但筛选仍然根据 query 找 BO”这类偏差。若一个 spec 包含多个来源候选，selector 按候选顺序或配置权重进行筛选并合并，最终仍遵守每类资源 limit。

替代方案是只用 `concept_name` 做检索。它无法承载账户 ID、账期 ID、返回余额字段等业务经验，因此不采用。

### Decision 4: 明确 fallback 边界和可观测状态

fallback 只在三类情况启用：无法生成 spec、spec 校验失败或标记不可用、spec 受约束筛选无法产出有效资源。selector 需要记录本次使用的是 `spec_guided` 还是 `query_fallback`，并保留失败原因，供测试和后续诊断使用。对外生成结果可以先不暴露该字段，但内部对象和测试替身必须能断言路径。

替代方案是 spec 和 query 筛选结果总是合并。该方案会削弱“spec 主导”的核心目标，也会让 query 中的简单概念重新压过业务经验，因此不采用。

### Decision 5: planner prompt 接收 spec 摘要，但资源仍是硬边界

`LLMPlanner.plan()` 可以增加可选 `nl_spec` 或 `spec_summary` 参数，用来解释概念、取值来源候选和 evidence。planner prompt 必须声明只能使用 `resources` 中提供的资源，不能根据 spec 编造未筛出的 BO、context、function 或 naming SQL。repair prompt 也需要同样约束。

替代方案是不把 spec 传给 planner，只传资源。这样能保证硬边界，但 planner 丢失了业务取值经验，例如优先上下文、其次 BO、最后 naming SQL 的偏好。第一版需要让自然语言规格约束 planner 生成，因此 planner 应读取 spec 摘要。

## Risks / Trade-offs

- 规格生成误判导致资源筛选过窄 -> 通过 strict validation、空结果 fallback、单元测试覆盖常见 CBS 和区域经验。
- prompt 变长影响 planner 稳定性 -> planner 只接收压缩后的 spec 摘要和已筛资源，不传完整知识库。
- `source_type` 映射不完整 -> 第一版先支持 `context`、`bo_field`、`naming_sql`、`function`，未知类型视为 spec 不可用或忽略并记录原因。
- 多个来源候选产生重复资源 -> selector 统一按 resource_id 去重，并保留现有限额控制。
- 旧调用方缺少 `region_type` 或 `cbs_name` -> 请求模型字段设为可选；缺失时直接走 query fallback。

## Migration Plan

1. 扩展 `ValueLogicRequest`，新增可选 `region_type` 和 `cbs_name` 字段，保持旧调用兼容。
2. 新增术语库和区域经验库 provider 接口及本地测试实现。
3. 新增 `NLSpec` 数据模型、生成器、校验逻辑和 prompt。
4. 新增 `SpecResourceSelector`，包装现有资源筛选机制并实现 fallback。
5. 将 `ValueLogicGenerator._generate_expression_by_plan()` 切换为 selector 入口。
6. 扩展 `LLMPlanner` 和 planner prompt，使 planner 可读取 spec 摘要但只能使用筛出的资源。
7. 增加单元测试和集成测试，覆盖 spec 主路径、三类 fallback、source_type 约束和 planner 资源边界。

回滚方式：禁用 `SpecResourceSelector` 或让缺省 provider 返回不可用 spec，即可回到现有 query 驱动筛选路径。

## Open Questions

- 术语库和区域经验库第一版的文件格式和目录位置是否沿用 `agent/resource_manager/data`，还是独立放在新的 knowledge data 目录？
- `value_source_candidates` 多个候选的默认优先级是否完全按数组顺序，还是需要给 `context` 默认更高优先级？
- `needs_business_knowledge=true` 时是否仍允许生成资源筛选结果，还是应强制 fallback 或抛出可诊断错误？
