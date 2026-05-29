# EDSL 生成系统设计文档

## 1. 文档目的

本文档说明当前 EDSL 生成项目的设计方案，帮助后续维护者理解系统如何把用户的自然语言需求、当前节点信息和项目资源转换为可执行的 EDSL 表达式。文档重点覆盖：

- 系统目标与非目标
- 核心链路与模块职责
- 关键数据模型
- LLM 参与点与降级策略
- 表达式生成、校验和扩展方式
- 当前风险与后续演进建议

## 2. 背景与目标

EDSL 生成系统服务于“给定某个 EDSL 节点及用户描述，自动生成该节点取值逻辑”的场景。输入通常包括站点、项目、节点路径、当前节点、父节点、用户需求，以及可选的完整 EDSL 树。系统需要结合项目内可用资源，生成以下几类结果：

| 结果类型 | 含义 | 典型场景 |
| --- | --- | --- |
| `expression` | 生成完整 EDSL 表达式 | 普通叶子节点、需要计算/格式化/查询的字段 |
| `bo_field_mapping` | 直接映射 BO 字段 | AB SQL 数据源字段和 BO 字段同名或可直接匹配 |
| `summary` | 汇总字段逻辑 | 明细字段求和、计数等汇总字段 |

系统的核心目标是：

1. 让 LLM 负责语义规划，而不是直接输出自由文本表达式。
2. 用结构化 Plan 和 AST 约束表达式生成，降低不可控输出风险。
3. 在资源筛选阶段尽量缩小上下文，降低 prompt 噪声和 token 成本。
4. 对资源筛选、复杂度路由等 LLM 能力提供可降级路径。

非目标：

1. 当前不负责完整 EDSL 文件生成，只处理单个节点的 value logic。
2. 当前不实现真实多租户远程资源读取，`site_id` 和 `project_id` 主要作为缓存 key。
3. 当前不在 AST 校验阶段做完整类型推导，只做结构和局部合法性校验。

## 3. 总体架构

系统以 `ValueLogicGenerator` 为主入口，分为资源准备、逻辑分流、资源筛选、LLM 规划、AST 构建、表达式渲染六个阶段。

```text
ValueLogicRequest
  -> ValueLogicGenerator.generate()
  -> ResourceLoader.load_resource()
  -> 判断是否 AB / summary / SQL 字段映射
  -> LLMDifficultyRouter.route_resources()
  -> build_filtered_environment()
  -> LLMPlanner.plan()
  -> build_ast()
  -> validate_ast()
  -> generate_expression()
  -> ValueLogicResult
```

主要模块职责如下：

| 模块 | 职责 |
| --- | --- |
| `agent/models.py` | 定义外部请求、节点信息和生成结果模型 |
| `agent/value_logic_generator.py` | 编排完整生成流程，处理 AB、summary、字段映射等业务分支 |
| `agent/resource_manager` | 从 JSON 和 EDSL tree 加载全局/局部资源 |
| `agent/environment` | 基于当前节点和用户需求筛选最相关资源 |
| `agent/planner` | 调用 LLM 生成结构化 Plan，并定义 Plan schema |
| `agent/expression_generation/ast` | 将 Plan 转换为 AST，校验后渲染为 EDSL 表达式 |
| `agent/llm` | 统一管理 prompt、模型配置、调用和 JSON 后处理 |

## 4. 输入输出模型

### 4.1 输入请求

`ValueLogicRequest` 是当前生成入口的主要输入：

| 字段 | 说明 |
| --- | --- |
| `site_id` | 站点 ID，用于资源缓存 key |
| `project_id` | 项目 ID，用于资源缓存 key |
| `node_path` | 当前节点在 EDSL tree 中的路径 |
| `node` | 当前节点原始 JSON |
| `parent_node` | 父节点原始 JSON，AB 字段分支会使用 |
| `query` | 用户自然语言需求 |
| `is_ab` | 是否按 AB 字段逻辑处理 |
| `edsl_tree` | 当前 EDSL 树，用于解析局部上下文 |

生成流程会把 `node` 转换为内部 `NodeDef`：

- `node_id`：来自 `node_id`、`id` 或 `field_id`
- `node_path`：直接来自请求
- `node_name`：优先来自 `node_name`、`field_name`、`name`，其次来自 `xml_name_property.xml_name`
- `description`：来自 `description` 或 `annotation`
- `is_ab`：来自节点自身标记

### 4.2 输出结果

`ValueLogicResult` 包含：

| 字段 | 说明 |
| --- | --- |
| `node_id` | 当前节点 ID |
| `logic_type` | `expression`、`bo_field_mapping` 或 `summary` |
| `expression` | 生成的表达式；summary 场景可为空 |
| `source` | 结果来源，说明来自 Plan、BO 字段或明细字段 |

这种设计让调用方可以区分“需要写入表达式”的结果和“由上层渲染器处理的结构化映射/汇总结果”。

## 5. 资源管理设计

资源管理层由 `ResourceLoader` 负责，当前加载四类资源：

| 资源类型 | 来源 | Registry |
| --- | --- | --- |
| Global Context | `context_definition.json` | `ContextRegistry` |
| BO | `bo_def_ootb.json` | `BoRegistry` |
| Function | `edsl_func.json` | `FunctionRegistry` |
| Local Context | `edsl_tree` | `LocalContextRegistry` |

全局资源按 `site_id:project_id` 缓存，局部上下文不缓存为固定列表，而是通过 `LoadedResource.get_visible_local_context_registry(node_path)` 按当前节点路径动态计算。这样可以保证不同节点看到不同祖先节点上定义的 `$local$` 和 `$iter$` 上下文。

资源加载后的重要设计点：

1. 所有 registry 都包含稳定的 `resource_id`，用于 LLM 筛选和后续引用。
2. loader 会为资源构建 `tag`，供本地启发式筛选使用。
3. 文件不存在时返回空资源，避免某类资源缺失导致整个流程失败。
4. JSON 顶层不是对象时抛出 `ValueError`，防止静默吞掉错误资源文件。

资源管理的详细说明可参考 `docs/resource-management.md`。当前该文档在终端输出中可能存在编码显示问题，但设计意图与代码实现对应。

## 6. 逻辑生成分流

`ValueLogicGenerator.generate()` 会先加载资源，再根据节点类型进入不同分支。

### 6.1 普通节点

当 `is_ab=False` 时，系统直接进入表达式规划链路：

```text
_generate_simple_leaf_expression()
  -> _generate_expression_by_plan()
```

### 6.2 AB 汇总字段

当 `is_ab=True` 且节点满足以下任一条件时，系统识别为汇总字段：

- `field_type` 归一化后为 `summary`
- `summary_type` 可归一化为 `sum` 或 `count`
- 存在 `summary` 或 `summary_config` 字典

汇总字段不会调用 LLM Planner，而是直接返回 `logic_type="summary"`，并在 `source` 中携带 `detail_field` 和 `summary_type`。

### 6.3 AB SQL 普通字段

当 `is_ab=True` 且父节点是 SQL 数据源时，系统会优先尝试 BO 字段直接映射：

1. 从父节点的 `ab_content.data_source.sql_query.bo_name` 读取 BO 名。
2. 在已加载 BO registry 中查找对应 BO。
3. 如果用户需求表达的是直接映射意图，并且当前字段名和 BO 字段名归一化后一致，返回 `bo_field_mapping`。
4. 如果无法映射，回退到表达式规划链路。

这条分支可以减少不必要的 LLM 调用，也能让简单字段映射结果更稳定。

## 7. 复杂度路由与资源筛选

表达式规划前，系统会调用 `LLMDifficultyRouter.route_resources()` 判断是否需要 BO 和函数资源。

| 路由结果 | BO | Function | 适用场景 |
| --- | --- | --- | --- |
| context only | 不使用 | 不使用 | 只需 `$ctx$`、`$local$`、`$iter$` |
| BO only | 使用 | 不使用 | 需要查表或 BO 字段 |
| function only | 不使用 | 使用 | 需要函数加工 |
| full | 使用 | 使用 | 复杂查询、加工或不确定场景 |

如果路由 LLM 不可用或异常，默认使用 full 路由，保证资源召回不被过早裁剪。

资源筛选由 `build_filtered_environment()` 完成，流程分为三层：

1. 本地 token 加权召回：基于用户需求、节点名和描述生成 weighted tokens。
2. 可选工具式搜索：LLM 生成 `resource_keyword_search` 命令，在候选资源名空间内进一步定位资源。
3. 可选 LLM 重排：LLM 在候选资源 ID 中选择最终资源；异常时回退本地排序。

本地召回的权重如下：

| 来源 | 权重 |
| --- | --- |
| 用户需求 | 3.0 |
| 节点名 | 2.0 |
| 节点描述 | 1.0 |

匹配分为精确匹配、子串匹配和模糊匹配。每类资源最多先保留 `top_n * 5` 个候选，且不超过 30 个。最终环境输出 `FilteredEnvironment`，其中包含已选中的 global context、local context、BO 和 function。

## 8. LLM 规划设计

`LLMPlanner` 不要求 LLM 直接写最终 EDSL 字符串，而是要求输出满足 `Plan` schema 的结构化 JSON。Plan 由一组表达式计划节点组成，支持：

| Plan 节点 | 说明 |
| --- | --- |
| `context_path` | 引用 `$ctx$`、`$local$`、`$iter$` 或 `it.` 路径 |
| `literal` | 字符串、数字、布尔值或空值 |
| `variable_ref` | 引用前面定义的变量 |
| `def` | 定义变量 |
| `compare` | 比较表达式 |
| `logical` | `and` / `or` 组合 |
| `call` | 普通函数调用 |
| `select` / `select_one` | BO 查询 |
| `fetch` / `fetch_one` | 命名 SQL 或函数式数据获取 |
| `return` | 返回最终值 |

Planner prompt 会接收：

- 用户需求
- 当前节点摘要
- 筛选后的资源摘要
- Plan JSON schema

如果 LLM 返回内容无法解析或不满足 schema，Planner 会调用 `planner_repair` prompt，带上无效结果和错误信息进行一次修复。

## 9. AST 与表达式渲染

Plan 通过 `build_ast()` 转换为内部 AST。AST 与 Plan 节点基本一一对应，但内部使用 `ProgramNode` 包装整个表达式程序。

转换后会调用 `validate_ast()` 做基础校验：

1. context path 和变量名不能为空。
2. `logical.items` 至少包含两个子表达式。
3. `call.name` 不能为空。
4. `exists()` 只能有一个参数。
5. `select` / `select_one` 的 filter 必须是 `compare` 或 `logical`。
6. `fetch` / `fetch_one` 参数名不能重复。
7. `return` 必须包含返回值。

最后 `generate_expression()` 将 AST 渲染为 EDSL 表达式。典型输出示例：

```text
select_one(BB_PREP_SUB, it.ID == $ctx$.id)
```

```text
def oid = fetch_one(E_RT_QUERY_BY_OFFERINGID, pair(it.OFFERING_ID, $ctx$.offeringId))
oid
```

函数调用还有一个补充步骤：`_qualify_function_resource_calls()` 会根据筛选出的函数资源补全函数类名。如果同名函数只对应一个 class，`CustCallMask(...)` 会被转换为 `DacsDataTrans.CustCallMask(...)`，避免最终表达式缺少命名空间。

## 10. LLM 配置与 Prompt 管理

LLM 配置由 `.env` 驱动，主要字段包括：

| 配置项 | 说明 |
| --- | --- |
| `ENABLE_LLM` / `ENABLE_LLM_RESOURCE_FILTER` | 是否启用 LLM |
| `OPENAI_API_KEY` | API key |
| `OPENAI_BASE_URL` | 可选 base URL |
| `OPENAI_BASE_MODEL` / `OPENAI_MODEL` | 基础模型 |
| `OPENAI_VL_MODEL` | 视觉模型，当前主流程未使用 |
| `OPENAI_TIMEOUT_SECONDS` | 调用超时 |

Prompt 由 `PromptManager` 从项目根目录的 `prompt.json` 加载，使用 `{{ variable }}` 占位符渲染。当前使用的 prompt key 包括：

- `difficulty_router`
- `resource_search_tool_trigger`
- `resource_filter`
- `planner`
- `planner_repair`

`generate_by_llm()` 负责渲染 prompt、选择模型、调用 `LLMClient.complete()`，并通过 `parse_json_response()` 把模型输出解析为字典。

## 11. 错误处理与降级策略

当前系统的降级路径主要集中在资源筛选和路由阶段：

| 场景 | 降级行为 |
| --- | --- |
| Difficulty Router 不可用或异常 | 默认 BO 和 Function 都可用 |
| Resource Search LLM 不可用或异常 | 跳过工具式搜索 |
| Resource Filter LLM 不可用或异常 | 使用本地启发式排序结果 |
| LLM 返回无效资源 ID | 忽略无效 ID，并用本地候选补齐 |
| Planner 返回无效 JSON 或 schema 不匹配 | 调用 repair prompt 修复 |
| AST 校验失败 | 抛出异常，由调用方处理 |

这意味着资源选择尽量“可降级”，但最终表达式规划仍依赖可用的 Planner。若未来需要完全离线运行，可以补充规则式 planner 或模板式兜底策略。

## 12. 测试覆盖

当前测试覆盖了系统的主要路径：

| 测试文件 | 覆盖重点 |
| --- | --- |
| `tests/test_value_logic_generator.py` | 主生成流程、AB summary、AB SQL 字段映射、资源路由 |
| `tests/test_environment.py` | 本地资源筛选、LLM 筛选降级、局部上下文 |
| `tests/test_llm_planner.py` | Planner 输入摘要、schema 校验和 repair |
| `tests/test_difficulty_router.py` | 复杂度路由响应归一化 |
| `tests/test_expression_ast_builder.py` | Plan 到 AST 的转换 |
| `tests/test_expression_validator.py` | AST 合法性校验 |
| `tests/test_expression_generator.py` | AST 到表达式渲染 |
| `tests/test_resource_loader.py` | 资源加载和缓存 |
| `tests/test_resource_search_tool.py` | 关键词搜索工具 |

修改核心链路后，建议至少运行：

```powershell
python -m unittest
```

如果只修改表达式生成链路，可优先运行：

```powershell
python -m unittest tests.test_value_logic_generator tests.test_llm_planner tests.test_expression_ast_builder tests.test_expression_validator tests.test_expression_generator
```

## 13. 扩展指南

### 13.1 新增 Plan / AST 节点

新增表达式能力时，建议按以下顺序修改：

1. 在 `agent/planner/models.py` 新增 Plan 节点模型，并加入 `ExprPlanNode` union。
2. 在 `agent/expression_generation/ast/nodes.py` 新增 AST 节点模型，并加入 `ExprNode` union。
3. 在 `builder.py` 增加 Plan 到 AST 的转换。
4. 在 `validator.py` 增加必要合法性校验。
5. 在 `generator.py` 增加表达式渲染逻辑。
6. 更新 `prompt.json` 中 planner 相关说明。
7. 增加 builder、validator、generator 和端到端测试。

### 13.2 新增资源类型

如果要增加 BO、Function、Context 之外的资源类型，需要同步改动：

1. 新增 registry 模型和 loader。
2. 扩展 `LoadedResource` 和 `ResourceLoader`。
3. 扩展 `FilteredEnvironment`。
4. 在 `build_filtered_environment()` 中加入候选召回和筛选。
5. 更新 `LLMResourceFilter.RESOURCE_GROUPS` 及资源摘要逻辑。
6. 更新 Planner 资源摘要和 prompt。
7. 增加资源加载、筛选和端到端生成测试。

### 13.3 接入真实项目资源

当前 `ResourceLoader.get_resource_data(site_id, project_id)` 仍从本地固定 JSON 文件读取资源。若要接入真实项目资源，建议把该方法改造成唯一的数据源适配点：

```text
site_id / project_id
  -> ResourceLoader.get_resource_data()
  -> remote config / project resource service / local override
  -> normalized payload
  -> registry loaders
```

这样可以保持 registry、environment、planner 和 AST 层稳定。

## 14. 当前风险与建议

1. `docs/resource-management.md` 在当前终端中显示为乱码，建议确认文件编码并修复为 UTF-8。
2. `prompt.json` 已在工作区中有未提交改动，且 prompt 对生成质量影响很大，建议将 prompt 变更纳入评审。
3. Planner 是最终表达式生成的强依赖，当前没有完全离线兜底方案。
4. AST 校验还没有做资源引用校验，例如 BO 名、函数名、context path 是否确实来自筛选环境。
5. `ResourceLoader` 缓存没有失效策略，资源文件或远程资源变化后需要明确刷新机制。
6. AB 字段直接映射依赖字段名归一化一致，复杂别名、大小写之外的语义映射仍会回退 Planner。
7. 当前 local context 输出字段名 `visible_local_context` 实际表示“筛选后的 local context”，如果后续需要同时保留全量可见上下文，建议拆分字段命名。

## 15. 一句话总结

当前 EDSL 生成系统采用“资源标准化 + 小上下文筛选 + LLM 结构化规划 + AST 受控渲染”的设计，让 LLM 主要承担语义理解和计划生成，最终表达式由代码路径稳定生成，从而在灵活性和可控性之间取得平衡。
