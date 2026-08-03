# Query 规格明确性前置判定实现计划

> **给 Claude：** 必需工作流：使用 test-driven-development 逐任务实现此计划。

**目标：** 表达式生成开始时只调用一次大模型判断 query 是否已是明确规格；明确则直接进入资源筛选，不明确则执行现有 SpecOrchestrator 规格生成逻辑。

**相关设计文档：** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** 新增独立 QuerySpecClarityAnalyzer，通过专用 prompt 返回严格布尔判定。ValueLogicGenerator 在 generation retry 循环外调用一次分析器，并把判定结果传入每次 attempt；明确分支复用现有 target generation/filter_resources，非明确分支保持现有 SpecOrchestrator/ResolutionCompiler 流程。

**技术栈：** Python、Pydantic、现有 LLMClient/prompt_manager、pytest

**范围 / 非范围：** 只增加 query 规格明确性 gate 和分流；不修改 SpecOrchestrator 内部递归求解，不修改 Planner/TypedContext，且不覆盖工作区已有未提交改动。

---

## Phase #1: 明确性判定与分流

### Task #1: 定义一次性 clarity gate 行为

**状态：** Finished

**文件：**
- 修改：`tests/test_value_logic_generator.py`
- 创建：`tests/test_query_spec_clarity.py`
- 功能：覆盖明确 query 直达资源筛选、不明确 query 进入 SpecOrchestrator、重试时只判定一次、非法模型输出安全进入 spec 生成。
- 实现说明：先写失败测试并确认失败来自缺少 analyzer 和分流逻辑。
- 预期验证结果：新增测试稳定 RED。

### Task #2: 实现 analyzer 与主链分流

**状态：** Finished

**文件：**
- 创建：`agent/spec_orchestration/spec_clarity.py`
- 修改：`agent/value_logic_generator.py`
- 修改：`prompt.json`
- 功能：一次判定后在 direct resource filtering 与 spec generation 之间分流。
- 实现说明：明确分支生成 `ExpressionSpec(nl=query)` 并复用资源筛选；不明确和无效输出采用现有 SpecOrchestrator；判定在 attempt 循环外执行。
- 预期验证结果：Task #1 测试转为 GREEN，现有两条路径契约保持兼容。

## Phase #2: 回归验证

### Task #3: 验证生成主链

**状态：** Finished

**文件：**
- 验证：`tests/test_query_spec_clarity.py`
- 验证：`tests/test_value_logic_generator.py`
- 验证：`tests/test_spec_orchestrator.py`
- 验证：`tests/test_planner_prompt.py`
- 功能：确认 gate、资源筛选、spec 生成与 prompt 契约无回归。
- 实现说明：运行定向测试和 diff 检查，保留用户已有未提交文件。
- 预期验证结果：相关测试全部通过。
