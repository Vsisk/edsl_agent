# Harness Capability Layer 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划。

**目标：** 为 Harness 增加通用 Tool / Skill / Knowledge 三类 Capability Registry，并让 ContextAssembler 统一把能力投影给 Stage。

**相关设计文档：** 当前用户需求，无独立批准设计文档。

**架构：** 在 `agent/expression_workflow` 下建立暂时的 harness capability 基础设施，保持通用模型不依赖 ExpressionWorkflow。ToolDefinition 只包装已有函数或可注入 callable；SkillDefinition 是 instruction/policy；KnowledgeDefinition 只管理 markdown/structured docs metadata 与按规则召回。

**技术栈：** Python dataclass、现有 WorkflowRuntime / ContextAssembler、pytest。

**范围 / 非范围：** 本轮实现注册、检索、装配与测试；不引入 embedding，不重写资源搜索、AST 校验、LLM prompt 业务实现。

---

## Phase #1: Capability Registry

### Task #1: Tool / Skill / Knowledge 通用模型

**状态：** Finished

**文件：**
- 创建：`agent/expression_workflow/capabilities.py`
- 修改：`agent/expression_workflow/__init__.py`
- 验证：`tests/test_capability_layer.py`

- 功能：定义 ToolDefinition、SkillDefinition、KnowledgeDefinition、ToolRegistry、SkillRegistry、KnowledgeRegistry。
- 实现说明：Registry 只做注册与检索；Tool 执行通过 `execute` callable 包装既有函数；Knowledge 按 metadata rule 匹配 workflow/stage/scope/tags 并支持 markdown 加载、去重和 priority 排序。
- 预期验证结果：注册重复时报错；检索可按 workflow/stage/tags 过滤；markdown 内容可懒加载。
- 完成时间：2026-09-15

## Phase #2: Expression 默认能力定义

### Task #2: 默认 Tool / Skill / Knowledge 注册

**状态：** Finished

**文件：**
- 创建：`agent/expression_workflow/expression_capabilities.py`
- 创建：`docs/knowledge/expression/*.md`
- 验证：`tests/test_capability_layer.py`

- 功能：提供 Expression Workflow 需要的默认工具名、三个 skill、六类 knowledge metadata。
- 实现说明：Tool 先使用可注入 callable 包装，不在此处重写业务搜索；默认 knowledge 指向 repo 内 markdown，内容保持短小规则化。
- 预期验证结果：resource_search / expression_generation / expression_repair 能按 stage 召回对应 skill 和 knowledge。
- 完成时间：2026-09-15

## Phase #3: ContextAssembler 接入

### Task #3: Stage ContextPolicy 声明 capabilities

**状态：** Finished

**文件：**
- 修改：`agent/expression_workflow/context.py`
- 修改：`agent/expression_workflow/definition.py`
- 修改：`tests/test_workflow_context_assembly.py`
- 验证：`tests/test_capability_layer.py`

- 功能：ContextPolicy 增加 tools/skills/knowledge 需求声明，ContextAssembler 按 policy 装配到 StageContext。
- 实现说明：Stage 不自行寻找 skill/markdown/tool；投影值默认写入 `tools`、`skills`、`knowledge`，并保留现有 Stage input 字段兼容。
- 预期验证结果：Assembler 输出的 StageContext 包含匹配的工具、技能和知识；未声明的能力不会泄漏。
- 完成时间：2026-09-15

## Phase #4: 验证与回归

### Task #4: 定向测试与 baseline

**状态：** Finished

**文件：**
- 验证：`python -m py_compile ...`
- 验证：`.venv\Scripts\python.exe -m pytest tests/test_capability_layer.py tests/test_workflow_context_assembly.py -q`
- 验证：`.venv\Scripts\python.exe -m pytest tests/test_value_logic_generator.py -q`

- 功能：证明 Capability Layer 通用可用，Expression 接入路径存在，记录 baseline 真实状态。
- 实现说明：不修复当前业务版缺失模块，除非它属于本轮 capability 边界。
- 预期验证结果：新增/既有 context assembly 测试通过；baseline 若仍失败，记录缺失模块。
- 完成时间：2026-09-15
