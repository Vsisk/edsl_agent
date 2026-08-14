# NamingSQL 条件参数类型链接实现计划

> **给 Claude：** 必需工作流：使用 test-driven-development 先写失败测试，再实现。
**目标：** 让 NamingSQL 条件参数能关联 BO field 类型，并在表达式输出时按参数类型渲染 char 与列表参数。

**相关设计文档：** 当前需求来自用户直接说明，无额外设计文档。

**架构：** 在 BO loader 阶段根据参数名与 BO field 名称做保守类型补全；在搜索候选输入中继续暴露补全后的参数类型；在表达式生成阶段提供类型感知的 fetch 参数渲染能力，避免全局改变普通字符串 literal 行为。

**技术栈：** Python、Pydantic、pytest、现有 AST/EDSL renderer。

**范围 / 非范围：** 本次只处理 NamingSQL 条件参数与同 BO field 的同名/规范化同名链接、char/string 单引号渲染、列表参数变量包装；不改 NamingSQL 选择算法与 SQL 执行语义。

---

## Phase #1: 参数类型链接

### Task #1: BO loader 参数补全

**状态：** Finished

**文件：**
- 修改：`agent/resource_manager/loader/bo_loader.py`
- 验证：`tests/test_resource_loader.py`
- 功能：当 NamingSQL param 与 BO property 能按名称匹配时，用 BO field 的 `data_type`、`data_type_name`、`is_list` 补全/覆盖参数类型。
- 实现说明：匹配使用大小写不敏感并忽略 `_` 的规范化名称，保持同 BO 内部链接，不跨 BO 推断。
- 预期验证结果：新增 loader 测试先失败后通过。

## Phase #2: 类型感知表达式输出

### Task #2: fetch 参数渲染约束

**状态：** Finished

**文件：**
- 修改：`agent/expression_generation/ast/nodes.py`
- 修改：`agent/expression_generation/ast/generator.py`
- 修改：`agent/planner/models.py`
- 验证：`tests/test_expression_generator.py`
- 功能：fetch/fetch_one 参数可携带类型信息；char/string literal 参数渲染为单引号；list 参数生成 `def <param>List: [value];` 后传变量。
- 实现说明：只在 fetch 参数上下文触发，不改变普通 literal 的双引号兼容行为。
- 预期验证结果：新增 AST 生成测试通过，既有 literal 测试不变。

## Phase #3: 候选输入回归

### Task #3: NamingSQL 搜索输入类型

**状态：** Finished

**文件：**
- 验证：`tests/test_spec_orchestrator_search.py`
- 功能：确认 NamingSQL candidate 的 `required_inputs` 使用补全后的参数类型。
- 实现说明：优先复用 loader 的补全结果，搜索侧不做重复推断。
- 预期验证结果：NamingSQL 搜索候选暴露 BO field 对齐后的类型。
