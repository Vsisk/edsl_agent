# Resource 搜索策略调整实现计划

> **给 Claude：** 使用 `test-driven-development` 逐任务实现此计划。

**目标：** 在唯一的 `SpecOrchestrator` 系统内调整 context、function、BO field、NamingSQL 与 select fallback 的搜索策略。

**相关设计文档：** 本轮讨论；`docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** 继续复用 `agent/spec_orchestration/search.py` 作为搜索入口。Context / Local Context 由代码执行关键词与 sklearn 余弦近似匹配；Function 由 LLM 基于全量 function 摘要选择候选；BO field 先由 LLM 在 BO domain 中缩小可能 BO，再在这些 BO 中按关键词匹配 field，后续仍由现有 BO access 搜索 NamingSQL，未找到时由现有 `BO_SELECT` fallback 接管。

**技术栈：** Python、Pydantic v2、sklearn、pytest、现有 `generate_by_llm` prompt 体系。

**范围 / 非范围：** 只修改现有 `SpecOrchestrator` 搜索策略和默认工厂注入；不恢复或新增 `agent/expression_spec`；不改 Planner。

---

## Phase #1: Context 搜索策略

### Task #1: context/local context 关键词余弦匹配

**状态：** Designed

**文件：**
- 修改：`agent/spec_orchestration/search.py`
- 修改：`tests/test_spec_orchestrator_search.py`

**功能：** Context 与 Local Context 使用请求关键词、别名、goal 语义和目标字段组成查询词，对 context 名称、注释、tag 生成文本，用 sklearn 余弦近似匹配排序。

**实现说明：** 保留精确路径/后缀匹配优先级；近似匹配作为关键词匹配的一部分，不依赖 embedding client。

**预期验证结果：** local context 被纳入搜索；弱拼写或 token 近似可以通过 sklearn cosine 命中；embedding client 不参与 context 搜索。

## Phase #2: Function 搜索策略

### Task #2: function 全量摘要交给 LLM selector

**状态：** Designed

**文件：**
- 修改：`agent/spec_orchestration/search.py`
- 修改：`agent/value_logic_generator.py`
- 修改：`prompt.json`
- 修改：`tests/test_spec_orchestrator_search.py`

**功能：** Function 数量不多时，默认生产路径将所有类型兼容的 function 摘要传给 LLM，由 LLM 返回候选 function id；搜索层按返回顺序生成 `ResourceCandidate`。

**实现说明：** 搜索层支持注入 `function_selector`，默认工厂注入基于 `generate_by_llm` 的 selector；无 selector 或 selector 无结果时保留确定性 fallback，保证离线测试可运行。

**预期验证结果：** 注入 fake selector 时能看到所有兼容 function 的 domain/name/description，并按 selector 返回顺序输出。

## Phase #3: BO field 与 NamingSQL 策略

### Task #3: BO field 先经 domain selector 缩小 BO

**状态：** Designed

**文件：**
- 修改：`agent/spec_orchestration/search.py`
- 修改：`agent/value_logic_generator.py`
- 修改：`prompt.json`
- 修改：`tests/test_spec_orchestrator_search.py`

**功能：** BO field 搜索先向 LLM 输入 BO domain 摘要，由 LLM 判断可能出现的 BO 表；field 匹配只在这些 BO 中执行。

**实现说明：** 搜索层支持注入 `bo_domain_selector`；如果 request 已指定 `target_bo_name`，优先使用该 BO；selector 无结果时回退到全部 BO，避免搜索断崖。

**预期验证结果：** fake selector 只返回一个 BO 时，field 搜索不会命中其他 BO 的同名/近似字段。

### Task #4: field 后续 NamingSQL 与 select fallback 保持现有流程

**状态：** Designed

**文件：**
- 验证：`tests/test_spec_orchestrator.py`
- 验证：`tests/test_spec_orchestrator_search.py`

**功能：** BO field commit 后继续用现有 BO_ACCESS 搜索 NamingSQL；若无合适 NamingSQL，继续回退 BO_SELECT select/select_one。

**实现说明：** 不新增流程节点，复用当前 `BO_ACCESS_TIER_ORDER`。

**预期验证结果：** 旧的 `bo_field_falls_back_to_select_one` 测试继续通过。

## Phase #4: 回归验证

### Task #5: 定向回归

**状态：** Designed

**文件：**
- 验证：`.\.venv\Scripts\python.exe -m pytest tests/test_spec_orchestrator_search.py tests/test_spec_orchestrator.py tests/test_value_logic_generator.py -q`

**功能：** 确认搜索策略调整不破坏现有 spec 求解、编译和 value logic 主链。

**实现说明：** 先跑单测 RED/GREEN，再跑定向集合。

**预期验证结果：** 新增测试和旧回归通过。
