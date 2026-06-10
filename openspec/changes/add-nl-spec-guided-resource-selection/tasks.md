## 1. 模型与知识接入

- [ ] 1.1 扩展 `ValueLogicRequest`，新增可选 `region_type` 和 `cbs_name` 字段，并保持旧调用兼容。
- [ ] 1.2 新增 `NLSpec`、`ValueSourceCandidate`、spec 状态或诊断结果等数据模型，覆盖必要字段校验。
- [ ] 1.3 新增术语库 provider 接口和本地测试实现，支持通过 `site_id + project_id + cbs_name` 获取 CBS 术语信息。
- [ ] 1.4 新增区域经验库 provider 接口和本地测试实现，支持通过 `site_id + project_id + region_type` 获取区域经验文本。
- [ ] 1.5 新增 NL Spec 生成 prompt 或本地组合逻辑，输入 `region_type + cbs_name + query + node + site_id + project_id`，输出固定 JSON 结构。

## 2. NL Spec 生成与校验

- [ ] 2.1 实现 `NLSpecGenerator`，整合术语信息、区域经验、query 和 node 信息生成 NL Spec。
- [ ] 2.2 实现 spec 可用性校验，拒绝非 JSON、缺少必要字段、候选为空、候选缺少 `source_type` 或 `nl` 的结果。
- [ ] 2.3 实现 fallback 诊断原因枚举，区分 spec 缺失、spec 不可用和 spec 筛选空结果。
- [ ] 2.4 添加 NL Spec 生成单元测试，覆盖账户余额示例、缺少 `region_type`、缺少 `cbs_name` 和结构不可用结果。

## 3. SpecResourceSelector

- [ ] 3.1 新增 `SpecResourceSelector`，作为资源筛选统一入口，先尝试 spec 主路径，再按条件回退到现有 query 驱动路径。
- [ ] 3.2 将 `value_source_candidates[].source_type` 映射为允许资源组：`context` 到 global/local context，`bo_field` 和 `naming_sql` 到 BO，`function` 到 function。
- [ ] 3.3 使用每个候选的 `source_type + nl` 构造受约束检索条件，并复用现有候选召回、明确资源名称匹配、语义匹配和候选合并能力。
- [ ] 3.4 实现多候选结果合并与 resource_id 去重，并继续遵守每类资源 limit。
- [ ] 3.5 确保 spec 主路径筛出有效资源时，原始 query 驱动筛选结果不会覆盖或扩展 spec 筛选结果。
- [ ] 3.6 添加 selector 单元测试，覆盖 spec 主路径、source_type 资源类型约束、未知 source_type、重复资源合并和三类 fallback。

## 4. 生成链路集成

- [ ] 4.1 修改 `ValueLogicGenerator._generate_expression_by_plan()`，使用 `SpecResourceSelector` 构建 filtered environment。
- [ ] 4.2 保留现有难度路由和动态 limit 逻辑作为 fallback 路径，并确认旧请求不传 `region_type` 或 `cbs_name` 时行为不变。
- [ ] 4.3 为 selector 结果保留内部路径状态，至少支持测试断言 `spec_guided`、`query_fallback` 和 fallback 原因。
- [ ] 4.4 扩展现有 `ValueLogicGenerator` 测试，验证 planner 收到的是 spec 筛选后的资源集合。

## 5. Planner 约束

- [ ] 5.1 扩展 `LLMPlanner.plan()` 和 repair 流程，接收可选 NL Spec 摘要。
- [ ] 5.2 更新 `prompt.json` 中 planner 和 planner_repair prompt，要求 planner 使用 spec 摘要理解业务取值经验，但只能引用 `resources` 中存在的资源。
- [ ] 5.3 添加 planner prompt 测试，验证 prompt 明确禁止编造未筛出的 BO、context、function 或 naming SQL。
- [ ] 5.4 添加 planner 行为测试或替身测试，验证 spec 存在时 planner 调用包含 spec 摘要，fallback 时仍能按旧资源集合运行。

## 6. 验证

- [ ] 6.1 运行 `python -m unittest tests.test_value_logic_generator tests.test_environment tests.test_llm_planner tests.test_planner_prompt`。
- [ ] 6.2 运行新增的 NL Spec 与 `SpecResourceSelector` 测试。
- [ ] 6.3 运行 `openspec status --change "add-nl-spec-guided-resource-selection"`，确认变更处于可实施状态。
- [ ] 6.4 手动检查账户余额示例：当 `region_type=basic_info` 且 `cbs_name=账户余额` 能生成可用 spec 时，资源筛选主路径由 spec 主导，planner 只接收 spec 筛出的资源。
