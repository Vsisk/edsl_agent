# 表达式生成重试机制实现计划

> **给 Codex：** 使用 `$test-driven-development` 按任务实现，并在结束前使用 `$verification-before-completion` 验证。

**目标：** 为表达式生成的 spec 生成、资源筛选、planner 和校验阶段增加统一的失败重试，默认最多尝试 3 次。

**相关设计文档：** 无；本次需求直接基于当前 `ValueLogicGenerator` 调用链实现。

**架构：** 保留资源加载与 context pack 的单次构建，将一次完整的表达式生成流水线封装为独立尝试。外层协调器对异常和结构化校验失败统一重试；成功立即返回，耗尽后保持现有异常或失败结果契约。

**技术栈：** Python、pytest、Pydantic

**范围 / 非范围：** 覆盖 spec、资源筛选、typed context/planner、解析与 AST 校验；不重试资源加载、context pack、汇总字段和直接 BO 字段映射；不引入退避等待或第三方重试依赖。

---

## Phase #1: 重试行为测试

### Task #1: 为各阶段失败补充回归测试

**状态：** Finished

**文件：**
- 修改：`tests/test_value_logic_generator.py`
- 功能：验证 spec、资源筛选、planner 异常会重试并最终成功，耗尽时抛出最后异常。
- 实现说明：使用有状态 fake 记录调用次数；以默认 3 次尝试为断言基准。
- 预期验证结果：新增测试在实现前因调用次数不足而失败。

### Task #2: 为校验失败补充回归测试

**状态：** Finished

**文件：**
- 修改：`tests/test_simple_expression_end_to_end.py`
- 功能：验证 parse/AST 校验失败会重新执行整条流水线，成功时返回表达式，耗尽时返回最后一次结构化失败。
- 实现说明：planner 或校验器按调用序列返回失败/成功结果。
- 预期验证结果：新增测试在实现前失败。

## Phase #2: 最小实现与回归

### Task #3: 实现统一尝试协调器

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`
- 功能：增加默认 3 次尝试的统一重试机制。
- 实现说明：抽取单次流水线；异常仅在最后一次重新抛出，`validation_failed` 仅在最后一次返回；非正整数配置拒绝初始化。
- 预期验证结果：新增测试和既有定向测试全部通过。

### Task #4: 完整验证

**状态：** Finished

**文件：**
- 验证：`tests/`
- 功能：确认重试机制未破坏既有生成、筛选、planner 和校验契约。
- 实现说明：先运行定向测试，再运行完整 pytest。
- 预期验证结果：所有测试退出码为 0。

## Phase #3: 错误反馈驱动的修复重试

### Task #5: 将上一轮失败反馈传入下一轮

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`
- 修改：`agent/environment/resource_filter.py`
- 修改：`agent/planner/simple_expression_planner.py`
- 修改：`agent/planner/llm_planner.py`
- 修改：`agent/llm/prompt_manager.py`
- 功能：下一轮 spec、资源筛选和 planner 可收到上一轮失败阶段、错误类型和错误消息；LLM prompt 明确要求基于该诊断修复。
- 实现说明：反馈内容采用有界 JSON；第一轮为空；保留不接受新参数的自定义组件兼容性；外部最终异常类型和消息保持不变。
- 预期验证结果：瞬时异常后的第二轮及校验失败后的第二轮均能观察到准确反馈。

### Task #6: 反馈链路回归验证

**状态：** Finished

**文件：**
- 修改：`tests/test_value_logic_generator.py`
- 修改：`tests/test_simple_expression_end_to_end.py`
- 修改：相关 prompt 测试
- 功能：验证反馈构造、长度限制、planner prompt 注入和兼容行为。
- 实现说明：先确认新增测试失败，再完成最小实现并运行完整 pytest。
- 预期验证结果：全量测试退出码为 0。
