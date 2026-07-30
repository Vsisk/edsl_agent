# If 条件表达式分解实现计划

> **给 Codex：** 按本计划使用测试驱动开发完成实现。

**目标：** 在现有受约束表达式分解中增加严格的 `if(condition, then, else)` 条件逻辑。

**相关设计文档：** `docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`

**架构：** 继续复用 `compose` 骨架和有序操作数，不引入任意 AST。`if` 必须恰好包含条件、成立值、否则值三个操作数；资源操作数作为独立 Goal 并行递归求解，固定字符串直接提交，最终按固定位置编译为条件逻辑。

**技术栈：** Python、Pydantic、ThreadPoolExecutor、pytest

**范围 / 非范围：** 支持单层受约束 if；条件作为一个语义 Goal 求解。暂不支持 LLM 输出任意比较 AST、嵌套表达式或省略 else。

---

## Phase #1: If 骨架契约

### Task #1: 模型、Prompt 与语义解析

**状态：** Finished

**文件：**

- 修改：`agent/spec_orchestration/models.py`
- 修改：`prompt.json`
- 验证：`tests/test_spec_orchestrator_semantic.py`
- 功能：接受 operator 为 `if` 且恰好三个有序操作数的组合。
- 实现说明：非法数量、额外字段和未知操作符继续降级为 single。
- 预期验证结果：合法 if 被解析；缺少 else 的 if 被拒绝。

## Phase #2: 递归求解与编译

### Task #2: If 分支求解和自然语言输出

**状态：** Finished

**文件：**

- 修改：`agent/spec_orchestration/orchestrator.py`
- 修改：`agent/spec_orchestration/compiler.py`
- 修改：`docs/design-docs/SpecOrchestratorRecursiveResolution_20260725.md`
- 验证：`tests/test_spec_orchestrator.py`
- 验证：`tests/test_spec_orchestrator_compiler.py`
- 功能：并行求解 condition、then、else 中的资源 Goal，并按固定位置生成条件逻辑。
- 实现说明：任一必要资源 Goal 失败则整体失败；Literal 不进入资源环境。
- 预期验证结果：条件与分支顺序稳定，最终资源列表包含三个成功分支使用的资源。
