# EDSL 表达式注释支持实现计划

目标：让表达式规划器明确要求 LLM 使用 `//` 或 `/* */` 注释，并让类型校验、表达式解析和生成链路安全支持行内、单行和多行注释。

## Stage #1：测试与语法边界

### Task #1：补充注释场景测试

**状态：** Designed

**文件：** `tests/test_edsl_expression_parser.py`、`tests/test_expression_generator.py`、`tests/test_planner_prompt.py`

**实现说明：** 覆盖字符串中的注释样式不应被误删，以及 `//`、`/* */` 在表达式开头、行内、单独一行和跨多行时不影响解析结果。

**预期结果：** 注释表达式与无注释表达式生成相同的规范化 EDSL；未闭合块注释给出明确错误。

## Stage #2：实现

### Task #2：共享注释清理逻辑

**状态：** Designed

**文件：** `agent/expression_generation/expression_syntax.py`、`agent/expression_generation/expression_type_validation.py`

**实现说明：** 在字符串、转义字符和注释状态之间进行扫描，安全移除两种注释，并复用到 parser 与 type validator，避免两层语法理解不一致。

### Task #3：接入 planner、parser 和 generator

**状态：** Designed

**文件：** `prompt.json`、`agent/planner/simple_expression_planner.py`、`agent/expression_generation/edsl_expression_parser.py`、`agent/expression_generation/ast/generator.py`

**实现说明：** planner prompt 要求表达式包含有意义的注释；parser 在进入现有语法分支前清理注释；generator 在输出表达式时统一处理表达式中的注释，避免注释改变运算边界。

**预期结果：** LLM 返回带注释的表达式可以正常通过计划解析、类型校验、AST 构建和生成。

## Stage #3：验证

### Task #4：运行定向与全量测试

**状态：** Designed

**验证：** `pytest tests/test_edsl_expression_parser.py tests/test_expression_generator.py tests/test_planner_prompt.py`，随后运行完整 `pytest`。

**预期结果：** 新增测试及既有回归测试全部通过。
