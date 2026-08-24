# Expression Spec 生成器轻量化实现计划

> **给 Claude：** 使用 `test-driven-development` 逐任务实现此计划。

**目标：** 按已给出的轻量化设计新增 Expression Context Spec 生成链路，保留 SearchRequestGenerator、ResourceSearchService、ExpressionSpecGenerator 三个核心模块。

**相关设计文档：** 用户附件 `Expression Spec 生成器轻量化设计`

**架构：** 在 `agent/expression_spec/` 下新增独立轻量模块，不替换现有 `agent/spec_orchestration/` 递归 Goal 流程。新链路以 `SpecDraft + SearchRequest` 为中间状态，资源搜索统一返回 `SearchResult`，最终由 `ExpressionSpecGenerator` 判断参数闭合并生成 `ExpressionContextSpec`。

**技术栈：** Python、Pydantic v2、pytest、asyncio。

**范围 / 非范围：** 本次实现轻量模块的模型、接口、闭合判断、依赖复用、批量搜索和主循环骨架；不实现真实 LLM prompt 生成，不改 Planner，不迁移旧生产入口。

---

## Phase #1: 轻量模型与接口

### Task #1: 新增模型与导出

**状态：** Designed

**文件：**
- 创建：`agent/expression_spec/models.py`
- 创建：`agent/expression_spec/__init__.py`
- 验证：`tests/test_expression_spec_lightweight.py`

**功能：** 定义 `TargetSpec`、`LogicRequirement`、`SpecDraft`、`SearchRequest`、`SearchResult`、`ResourceBinding`、`ExpressionContextSpec`、`MissingRequirement`、`SpecGenerationResult` 和入口请求模型。

**实现说明：** 使用 `Literal` 收紧枚举值，所有可变默认值使用 `Field(default_factory=...)`，避免提前引入 EDSL AST 结构。

**预期验证结果：** 模型可被校验和序列化；`SearchRequest` 不共享默认 `constraints`；`ExpressionContextSpec` 只包含业务逻辑和资源绑定。

## Phase #2: 三模块实现

### Task #2: SearchRequestGenerator

**状态：** Designed

**文件：**
- 创建：`agent/expression_spec/search_request_generator.py`
- 验证：`tests/test_expression_spec_lightweight.py`

**功能：** 提供 `generate_initial()` 和 `generate_followup()`。初始生成通过可注入 planner 函数返回 `SpecDraft` 与搜索请求；follow-up 将 `MissingRequirement` 标准化为 `SearchRequest`。

**实现说明：** follow-up 复用缺失项的 `resource_types`、`semantic`、`scope`、`expected_return_type` 和 `introduced_by`，并从语义文本生成保守关键词。

**预期验证结果：** Function 参数缺失如 `BC_ACCT` 能转换成 context 搜索请求，并保留追踪信息。

### Task #3: ResourceSearchService

**状态：** Designed

**文件：**
- 创建：`agent/expression_spec/resource_search_service.py`
- 验证：`tests/test_expression_spec_lightweight.py`

**功能：** 提供异步 `search()` 与 `search_batch()`，按 `resource_types` 调用可注入 searcher，并并发处理同一轮请求。

**实现说明：** 每种资源类型是一个 async 或 sync callable；搜索失败不抛出到主循环，而返回 `success=False` 的 `SearchResult`。

**预期验证结果：** 多个请求能并发完成；selected_resource 保留完整签名。

### Task #4: ExpressionSpecGenerator

**状态：** Designed

**文件：**
- 创建：`agent/expression_spec/expression_spec_generator.py`
- 验证：`tests/test_expression_spec_lightweight.py`

**功能：** 将成功搜索结果绑定回 `logic_requirements`，检查 Function/NamingSQL 必需参数来源，复用已解析依赖，闭合后生成 `ExpressionContextSpec`，未闭合时返回 `MissingRequirement`。

**实现说明：** 参数来源优先级为 `draft.known_values`、上下文对象中的已知资源、已解析语义绑定；参数名归一化后复用同名依赖。

**预期验证结果：** `BILL_CYCLE_ID` 与 `PREPARE_ID` 被多个资源使用时只解析一次；缺失参数会返回 follow-up 所需描述。

## Phase #3: 主循环与验证

### Task #5: 主入口服务

**状态：** Designed

**文件：**
- 创建：`agent/expression_spec/workflow.py`
- 验证：`tests/test_expression_spec_lightweight.py`

**功能：** 提供 `ExpressionSpecWorkflow.generate_spec()`，按设计执行获取 context、初始搜索、批量搜索、闭合判断和 follow-up 搜索循环。

**实现说明：** 注入 `context_manager` 和三个核心模块；使用 `max_rounds` 防止无限循环；无可继续请求时抛出 `SpecGenerationError`。

**预期验证结果：** 两轮搜索场景可最终生成闭合 spec；无闭合路径时抛出明确错误。

### Task #6: 回归验证

**状态：** Designed

**文件：**
- 验证：`pytest tests/test_expression_spec_lightweight.py`
- 验证：`pytest tests/test_spec_orchestrator*.py tests/test_expression_spec.py`

**功能：** 确认新增轻量链路自身通过，并且不破坏旧 spec orchestration 和现有 expression spec 模型。

**实现说明：** 优先运行定向测试；若旧测试因历史编码文本失败，只记录与本次变更无关的失败点。

**预期验证结果：** 新增测试全绿；旧相关测试无新增回归。
