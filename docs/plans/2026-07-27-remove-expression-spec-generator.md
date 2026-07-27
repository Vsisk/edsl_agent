# 移除 ExpressionSpecGenerator 实现计划

> **给 Codex：** 按本计划使用测试驱动开发完成实现。

**目标：** SpecOrchestrator 不再接收或生成 base spec，最终 `ExpressionSpec` 完全由递归求解结果编译产生。

**相关设计文档：** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** `SpecOrchestrator` 负责 Goal 生成、资源搜索和递归求解；`request` 与 `context_pack` 作为 LLM 语义判断的背景输入，但不参与代码控制的搜索分支。`ResolutionCompiler` 根据 query、root goal 和 committed resolution 生成自然语言 Spec 与筛选资源，不生成或传递基础 Spec。

**技术栈：** Python、Pydantic、pytest

**范围 / 非范围：** 删除新编排链路中的 `ExpressionSpecGenerator` 依赖和 `base_spec` 数据；保留 `ExpressionSpec` 作为下游 Planner 的稳定输入模型，不改公开 `ValueLogicResult`。

---

## Phase #1: 收紧编排结果契约

### Task #1: 删除 base spec

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/models.py`
- 修改：`agent/spec_orchestration/orchestrator.py`
- 验证：`tests/test_spec_orchestrator.py`
- 功能：结果只携带原始 query、Goal、求解树和筛选轨迹。
- 实现说明：移除 `base_spec` 和 generator 注入点；保留 `request`、`context_pack`，由语义网关安全序列化后注入 prompt。
- 预期验证结果：Orchestrator 无需构造或注入 ExpressionSpecGenerator 即可递归求解。

## Phase #2: 直接生成最终 Spec

### Task #2: 编译递归求解结果

**状态：** Finished

**文件：**
- 修改：`agent/spec_orchestration/compiler.py`
- 验证：`tests/test_spec_orchestrator_compiler.py`
- 功能：有 resolution 时输出资源编排自然语言；无 resolution 时以 query 作为可继续消费的 Spec。
- 实现说明：`ExpressionSpec` 使用自身默认 scope/skills，不继承不存在的基础 Spec。
- 预期验证结果：最终 Spec 与筛选资源来自同一 committed resolution。

## Phase #3: 清理主链调用

### Task #3: 移除新链路 generator 参数

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`
- 验证：`tests/test_value_logic_generator.py`
- 功能：主链向 Orchestrator 传 node info、query、expected type、node path，以及作为语义背景的 request、context pack。
- 实现说明：删除构造参数和所有调用点；旧兼容路径直接以 query 构造稳定的 `ExpressionSpec` 数据对象。
- 预期验证结果：专项测试和完整测试通过，主链调用参数中不存在 base spec、request 或 context pack。
