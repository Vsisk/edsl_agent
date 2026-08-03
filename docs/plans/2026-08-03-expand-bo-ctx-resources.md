# BO 与 CTX 返回类型资源展开实现计划

> **给 Claude：** 必需工作流：使用 test-driven-development 逐任务实现此计划。

**目标：** 先加载 logic 与 extra 类型资源，并让 BO、CTX 按字段 return type 递归展开，注册根属性及沿途所有可访问属性路径。

**相关设计文档：** 无；以本次用户需求和现有资源模型为准。

**架构：** 在资源加载层建立统一的结构化类型索引与递归展开器。ResourceLoader 先解析 logic/extattr，再用类型索引加载 BO，最后把 BO 类型加入索引并加载 CTX；展开过程保留原始根资源，并为每个嵌套字段生成点路径资源，同时检测循环引用。

**技术栈：** Python、Pydantic、unittest/pytest

**范围 / 非范围：** 仅调整 BO/CTX 注册表加载及其测试；不修改资源筛选、表达式生成和用户当前未提交的 typed context/planner 改动。

---

## Phase #1: 返回类型展开

### Task #1: 用失败测试定义 BO/CTX 展开行为

**状态：** Finished

**文件：**
- 修改：`tests/test_resource_loader.py`
- 功能：覆盖 BO 字段引用 extattr、CTX 引用 BO/logic、递归多层展开、父路径保留及循环引用终止。
- 实现说明：先运行定向测试确认新增断言因当前加载器不展开而失败。
- 预期验证结果：新增测试稳定 RED，失败原因是缺少嵌套路径资源。

### Task #2: 实现统一类型索引与有序加载

**状态：** Finished

**文件：**
- 创建：`agent/resource_manager/loader/type_expander.py`
- 修改：`agent/resource_manager/loader/bo_loader.py`
- 修改：`agent/resource_manager/loader/context_loader.py`
- 修改：`agent/resource_manager/loader/resource_loader.py`
- 功能：按 return type 展开 BO/CTX，并注册根与所有嵌套路径。
- 实现说明：logic/extattr 优先加载；BO 原始字段形成 BO 类型定义；递归展开支持 bo/logic/extattr/list，使用当前类型路径集合截断循环；生成结果保持稳定顺序和唯一名称。
- 预期验证结果：Task #1 新增测试转为 GREEN，既有 loader 测试保持通过。

## Phase #2: 回归验证

### Task #3: 定向与相关测试回归

**状态：** Finished

**文件：**
- 验证：`tests/test_resource_loader.py`
- 验证：`tests/test_typed_expression_context.py`
- 功能：确认加载层行为和下游 typed context 消费兼容。
- 实现说明：先运行资源加载测试，再运行相关表达式上下文测试；不覆盖工作区已有改动。
- 预期验证结果：定向测试全部通过，无新增回归。
