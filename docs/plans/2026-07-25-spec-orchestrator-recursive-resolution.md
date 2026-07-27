# SpecOrchestrator 递归求解实现计划

> **给 Codex：** 必需工作流：按本计划逐任务使用测试驱动开发完成实现。

**目标：** 用代码控制、LLM 辅助的 `SpecOrchestrator` 替换 Value Logic 主链中一次性 Spec/资源筛选/NamingSQL 决策流程，并继续向现有 Planner 输出 `ExpressionSpec` 和 `FilteredEnvironment`。

**相关设计文档：** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** 新增独立 orchestration 包，内部维护轻量 Goal/Resolution 状态和固定搜索层级；搜索适配器复用现有 `LoadedResource`、Registry、环境过滤与 NamingSQL Retriever；编译器只把 committed resolution 投影成现有下游模型。`ValueLogicGenerator` 仅替换普通表达式生成中段，TypedContext、Planner、Validator、AST 和 Renderer 保持原契约。

**技术栈：** Python、Pydantic、dataclasses、现有 LLM gateway、pytest/unittest。

**范围 / 非范围：** 实现 Goal、分层搜索、LLM 双重保护、依赖递归、主键关系、Spec/环境编译和主链集成；不修改公开 `ValueLogicResult`、Planner/AST Schema，不引入外部数据库或新向量服务。

---

## Stage #1: 编排领域模型与确定性搜索

### Task #1: Goal、候选和状态契约

**状态：** Finished

**文件：**
- 创建：`agent/spec_orchestration/models.py`
- 创建：`agent/spec_orchestration/__init__.py`
- 验证：`tests/test_spec_orchestrator_models.py`
- 功能：定义 Goal、搜索层级、覆盖决策、候选引用、依赖绑定、Resolution 和 Orchestrator 结果。
- 实现说明：模型只保存现有 Registry 对象引用和轻量元数据；严格限制覆盖枚举和候选 ID；避免复制现有资源定义。
- 预期验证结果：非法状态、未知覆盖类型、空候选引用和可变默认值被拒绝，合法 Root/Dependency Goal 可稳定构造。

### Task #2: 资源搜索门面与适配器

**状态：** Finished

**文件：**
- 创建：`agent/spec_orchestration/search.py`
- 验证：`tests/test_spec_orchestrator_search.py`
- 功能：按代码指定层级搜索 Context/Local、BO 字段、NamingSQL、Function 和主键关系。
- 实现说明：直接复用 `LoadedResource`、`get_visible_local_context_registry()`、Registry 字段和 `NamingSqlCandidateRetriever`；`data_type=key` 识别主键；跨 BO 关系要求字段名、基础类型和基数兼容。
- 预期验证结果：搜索只返回 Registry 中资源；联合主键完整识别；NamingSQL 和 Function 暴露真实参数；搜索层级不能由 LLM 改写。

## Stage #2: LLM 网关与双重保护

### Task #3: Goal、关键词和覆盖判断网关

**状态：** Finished

**文件：**
- 创建：`agent/spec_orchestration/semantic.py`
- 修改：`prompt.json`
- 验证：`tests/test_spec_orchestrator_semantic.py`
- 功能：提供严格的 Goal 生成、当前层关键词生成和候选覆盖判断。
- 实现说明：网关使用注入式 callable 便于测试；只发送有界摘要和 opaque ID；响应通过 Pydantic 严格校验。
- 预期验证结果：未知 ID、重复 ID、非法枚举、缺失字段和超长输出均被拒绝；LLM 无法指定工具或搜索层级。

### Task #4: 硬校验和故障语义

**状态：** Finished

**文件：**
- 创建：`agent/spec_orchestration/validation.py`
- 验证：`tests/test_spec_orchestrator_validation.py`
- 功能：校验资源真实性、字段、类型、基数、参数、联合主键、作用域和依赖循环。
- 实现说明：提交采用 fail-closed；覆盖判断失败采用 not-cover 并继续搜索；所有 ID 重新映射到请求级 Registry。
- 预期验证结果：LLM 即使声明 cover，也无法提交不存在资源、错误字段、类型冲突或未完整绑定的联合主键。

## Stage #3: 递归状态机与结果编译

### Task #5: SpecOrchestrator 递归求解

**状态：** Finished

**文件：**
- 创建：`agent/spec_orchestration/orchestrator.py`
- 验证：`tests/test_spec_orchestrator.py`
- 功能：实现固定 P0-P4 层级、候选分支、Dependency Goal、回滚、循环和预算。
- 实现说明：代码触发每层搜索；LLM只生成关键词和覆盖判断；依赖来自真实 NamingSQL/Function 参数或 BO 主键；失败分支不污染 committed state。
- 预期验证结果：Context 命中后不触发低层搜索；依赖链可递归闭合；失败候选回滚；循环和预算稳定终止。

### Task #6: 自然语言 Spec 和 FilteredEnvironment 编译

**状态：** Finished

**文件：**
- 创建：`agent/spec_orchestration/compiler.py`
- 验证：`tests/test_spec_orchestrator_compiler.py`
- 功能：从 committed resolution 同时生成 `ExpressionSpec` 和 `FilteredEnvironment`。
- 实现说明：保留基础 spec 的 scope/skills；裁剪 BO 字段和 NamingSQL；构造兼容 NamingSQL Selection；只输出 committed 资源。
- 预期验证结果：Spec 与资源环境引用同一链路；失败候选不出现；现有 Planner 摘要和 NamingSQL Validator 可消费输出。

## Stage #4: Value Logic 主链集成与回归

### Task #7: 接入 ValueLogicGenerator

**状态：** Finished

**文件：**
- 修改：`agent/value_logic_generator.py`
- 验证：`tests/test_value_logic_generator.py`
- 功能：普通表达式路径调用 Orchestrator，并移除主链中独立的一次性资源筛选和 NamingSQL 最终决策。
- 实现说明：保留 ContextPack 单次构建、summary 和 BO 直接映射快速路径、TypedContext/Planner/AST 后半链；允许注入 fake Orchestrator。
- 预期验证结果：调用顺序为 ContextPack -> Orchestrator -> TypedContext -> Planner；现有公开结果不变。

### Task #8: 端到端递归场景与整体回归

**状态：** Finished

**文件：**
- 创建：`tests/test_spec_orchestrator_end_to_end.py`
- 验证：`tests/test_value_logic_generator.py`
- 功能：覆盖 Context 直取、NamingSQL 参数递归、BO 主键跨表和 Function 参数递归。
- 实现说明：全部 LLM 使用确定性 fake；断言工具调用顺序、候选边界、自然语言 Spec、最终资源和 EDSL 生成。
- 预期验证结果：定向测试和完整 `pytest -q` 通过；无未授权资源进入 Planner；计划状态回写为 Finished。
