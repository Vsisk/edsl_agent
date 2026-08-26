# business path 系统上下文实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 在 value logic 请求最初进入时，根据 `node_path` 解析当前节点链路上的 XML name，形成 business path，并推断账单级、账户级或用户级后放入系统上下文向下传递。

**相关设计文档：** 当前对话需求。

**架构：** 在入口侧新增一个轻量 business context 构建器，由 `ValueLogicGenerator.generate()` 调用，并通过现有 `ContextPackRequest` / `ContextPack` 传给 spec orchestration、compiler、planner 等后续链路。保持单一 spec orchestration 系统，不新增独立 spec 生成流程。

**技术栈：** Python、Pydantic、jsonpath-ng、pytest。

**范围 / 非范围：** 本次只实现 business path 与节点层级上下文注入；不调整资源搜索策略、spec 编译规则或 LLM prompt 语义。

---

## Phase #1: 入口上下文建模

### Task #1: business path 解析与层级判断

**状态：** Finished

**文件：**
- 创建：`agent/business_context.py`
- 验证：`tests/test_business_context.py`

**功能：** 从 `edsl_tree` 和 `node_path` 解析链路节点，提取链路上所有 `xml_name_property.xml_name`，生成 `business_path` 与可读的 `business_path_text`，并交给 LLM 判断当前节点 scope。

**实现说明：** 使用轻量 JSONPath token 解析 `node_path` 并回溯链路节点；如果 tree/path 不可用，则回退到当前节点。scope 判断不使用本地名称规则，统一通过 `business_scope_classifier` LLM prompt 输出 `bill`、`acct` 或 `sub`；LLM 不可用时返回稳定默认值 `sub`，避免入口中断。

**预期验证结果：** 单元测试覆盖正常路径、缺失 tree/path 回退、LLM classifier 入参和 scope 输出。

## Phase #2: 系统上下文传递

### Task #2: ContextPackRequest 与 ContextPack 携带 system_context

**状态：** Finished

**文件：**
- 修改：`agent/context_pack/models/request.py`
- 修改：`agent/context_pack/models/pack.py`
- 修改：`agent/context_pack/builder.py`
- 验证：`tests/test_context_pack_models.py`、`tests/test_context_pack_builder.py`

**功能：** 让 context pack 请求和产物都能承载 `system_context`，并在构建时复制传递。

**实现说明：** 增加默认空字典字段，保持向后兼容；builder 在 `request_summary` 中保留摘要，同时把完整上下文放到 `ContextPack.system_context`。

**预期验证结果：** 旧测试无需调整即可通过，新测试确认 `system_context` 被保留。

## Phase #3: ValueLogicGenerator 入口接入

### Task #3: 请求入口创建并下传系统上下文

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`
- 验证：`tests/test_value_logic_generator.py`

**功能：** 在请求最先进入 `generate()` 时构建 business context，写入 `ContextPackRequest.system_context`，后续 planner/spec orchestrator 通过已有 `context_pack` 获得同一份上下文。

**实现说明：** 在加载资源和构建 context pack 前调用 helper；不改变 resource router 和 orchestrator 的调用接口。

**预期验证结果：** 生成请求中的 node path 能在 pack request 和 planner 收到的 context pack 中看到同样的 business path 与 level。
