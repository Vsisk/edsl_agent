## Why

当前资源筛选主要由用户原始 query 驱动。当 SA 在需求中只给出很短的业务描述时，系统容易把业务概念理解得过窄，导致筛出的 BO、context、function 与实际开发规格存在明显偏差。现在需要在资源筛选前引入术语库和区域经验库，把 `region_type + cbs_name + query + node + site_id + project_id` 转换成可用的自然语言规格，并用该规格主导后续资源筛选和 planner 生成。

## What Changes

- 新增 NL Spec 生成能力：基于 `region_type` 获取对应区域经验库，基于 `cbs_name` 获取对应 CBS 术语，并结合原始 query 与当前 node 生成自然语言规格。
- 定义第一版 NL Spec 输出契约，包含 `concept_id`、`concept_name`、`semantic_type`、`region_type`、`value_source_candidates`、`evidence`、`needs_business_knowledge`。
- 新增 `SpecResourceSelector` 包装现有资源筛选机制：保留难度路由、明确资源名称匹配、语义匹配和候选合并，但由 spec 约束搜索空间、资源类型和参数来源。
- 调整资源筛选优先级：只要能够基于 `region_type + cbs_name` 生成可用规格，后续资源筛选必须以该规格为主导；planner 只能使用规格筛选出的资源。
- 保留退化路径：当规格缺失、规格不可用或规格无法筛出有效资源时，回退到当前 query 驱动的资源筛选逻辑。
- 明确第一版非目标：不进行本体推理、复杂概念识别、强结构化 BO 参数规划，先用自然语言规格承载业务取值经验。

## Capabilities

### New Capabilities

- `nl-spec-guided-resource-selection`: 定义从术语库和区域经验库生成 NL Spec，并用该规格约束资源筛选与 planner 的行为。

### Modified Capabilities

## Impact

- Affected code:
  - `agent/value_logic_generator.py`
  - `agent/environment/environment.py`
  - `agent/environment/resource_filter.py`
  - `agent/planner/llm_planner.py`
  - `prompt.json`
  - resource loading or knowledge loading modules under `agent/resource_manager/`
  - related tests under `tests/`
- Affected behavior:
  - 资源筛选的主输入从原始 query 优先切换为可用 NL Spec。
  - planner 的可用资源范围受 NL Spec 筛选结果约束。
  - 当前 query 驱动筛选逻辑变为 fallback，而不是默认主路径。
- External dependencies:
  - 第一版不要求新增外部服务依赖；术语库和经验库可以先通过本地 loader 或可注入 provider 接入。
