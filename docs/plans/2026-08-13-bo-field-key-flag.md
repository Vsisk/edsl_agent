# BO Field 主键标记实现计划

> **交接：** 使用实现计划逐项完成本计划。
**目标：** 解析 BO 字段时将 `data_type=key` 规范化为 `data_type=basic` 并设置 `is_key=true`，BO select 仅依据 `is_key` 识别主键。

## Phase #1: 模型与解析

### Task #1: 扩展 PropertyTerm 并规范化 key

**状态：** Designed

**文件：** `agent/resource_manager/loader/registry_models.py`

**实现说明：** 增加 `is_key` 字段；模型构造时兼容旧输入 `data_type=key`，自动转为 `basic` 并标记主键。

**预期结果：** 新旧 BO JSON 输入均得到统一的字段模型。

### Task #2: 调整 BO select 主键筛选

**状态：** Designed

**文件：** `agent/spec_orchestration/search.py`

**实现说明：** 主键判断统一使用 `field.is_key`，字段返回类型保持 `basic`。

**预期结果：** select fallback 与候选字段元数据正确反映主键标记。

## Phase #2: 测试与验证

### Task #3: 补充回归测试并运行相关测试

**状态：** Designed

**文件：** `tests/test_resource_loader.py`、`tests/test_spec_orchestrator_search.py`

**实现说明：** 覆盖 key 解析规范化、普通字段默认值及 select 主键选择。

**预期结果：** 相关 pytest 测试通过。
