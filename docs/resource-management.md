# 资源管理方法说明

## 文档目的

本文档说明当前 EDSL 生成项目中的资源管理方法，帮助后续维护者理解资源从原始 JSON 到可筛选环境的完整链路。读者预期是需要维护 `agent/resource_manager`、扩展资源类型、调整资源筛选策略，或排查生成 DSL 时资源缺失问题的开发者。

## 总体链路

当前资源管理由两层组成：

1. 资源加载层：`ResourceLoader` 从 JSON 数据源读取全局资源，并归一化为 registry 对象。
2. 环境筛选层：`build_filtered_environment` 基于用户需求和当前 EDSL 节点，从 registry 中选出本次生成 DSL 最相关的资源。

核心数据流如下：

```text
JSON 资源文件
  -> ResourceLoader.get_resource_data()
  -> context / bo / function loader
  -> LoadedResource
  -> build_filtered_environment()
  -> FilteredEnvironment
  -> 后续 planner / validator / ast builder / renderer
```

其中，全局资源会按 `site_id:project_id` 缓存；局部上下文资源不进入全局缓存，而是在调用 `LoadedResource.get_visible_local_context_registry(node_path)` 时根据当前 EDSL tree 和节点路径动态计算。

## 资源类型

当前系统管理四类资源。

| 类型 | 来源 | Registry 模型 | 主要用途 |
| --- | --- | --- | --- |
| Global Context | `context_definition.json` | `ContextRegistry` | 表示可通过 `$ctx$...` 访问的全局上下文字段 |
| BO | `bo_def_ootb.json` | `BoRegistry` | 表示业务对象、字段、命名 SQL |
| Function | `edsl_func.json` | `FunctionRegistry` | 表示可调用函数、所属类、参数和返回值 |
| Local Context | `edsl_tree` | `LocalContextRegistry` | 表示当前节点可见的 `$local$...` 和 `$iter$...` 上下文 |

这些模型统一定义在 `agent/resource_manager/models/registry_models.py`，每个 registry 都包含稳定的 `resource_id`、可展示/调用的名称、结构化元数据，以及用于初筛的 `tag`。

## 数据加载与缓存

`ResourceLoader` 的默认数据目录是 `agent/resource_manager/data`，默认读取三份文件：

| 常量 | 文件 | 内容 |
| --- | --- | --- |
| `CONTEXT_FILE` | `context_definition.json` | 全局上下文定义 |
| `BO_FILE` | `bo_def_ootb.json` | 系统 BO、自定义 BO、字段、命名 SQL |
| `FUNCTION_FILE` | `edsl_func.json` | 脚本函数和 native 函数 |

加载入口是 `load_resource(site_id, project_id, edsl_tree)`。它会先调用 `get_resource_data()` 读取原始 payload，再以 `site_id:project_id` 作为 `source_key` 分别缓存三类全局 registry：

- `context_registry_cache`
- `bo_registry_cache`
- `function_registry_cache`

文件缺失时 `_read_json_file()` 返回空字典，因此某类资源可以为空；如果 JSON 顶层不是对象，则会抛出 `ValueError`。当前 `get_resource_data(site_id, project_id)` 还没有真正根据站点或项目切换数据源，只是保留了参数位置，后续可以在这里接入远程配置、项目级覆盖或多租户资源目录。

`load_resource()` 返回 `LoadedResource`，其中包含三类全局 registry 和调用方传入的 `edsl_tree`。局部上下文依赖 `edsl_tree` 和当前节点，所以它被放在 `LoadedResource.get_visible_local_context_registry(node_path)` 中按需计算。

## 全局上下文加载

`context_loader` 处理 `global_context` 和 `sub_global_context` 两个根节点。加载逻辑会递归遍历上下文树，直到遇到不可展开的叶子节点才生成 `ContextRegistry`。

可展开类型定义为：

```python
EXPANDABLE_DATA_TYPES = {"bo", "logic", "extattr"}
```

因此，当一个节点的 `return_type.data_type` 是 `bo`、`logic` 或 `extattr` 时，loader 会继续向下展开子节点；当它是基础类型或其他不可展开类型时，当前路径会被注册为一个可用上下文资源。

每个 `ContextRegistry` 的关键字段如下：

- `resource_id`：按加载顺序生成，格式为 `ctx.0000`。
- `context_name`：由路径拼接得到，例如 `$ctx$.billStatement.BE_ID`。
- `return_type`：沿用原始节点的返回类型。
- `property_type`：使用当前节点的 `property_type`；若没有则继承父节点；最终默认 `custom`。
- `annotation`：将路径上的 annotation 用 `.` 拼接，保留层级语义。
- `tag`：由字段名、属性类型、annotation、上层路径和类型名构成，用于后续资源筛选。

## BO 加载

`bo_loader` 会把 `sys_bo_list` 和 `custom_bo_list` 统一拉平成 `BoRegistry` 列表，并按 BO 名称构建字典。

每个 BO 会包含：

- `resource_id`：按加载顺序生成，格式为 `bo.0000`。
- `bo_name` / `bo_desc`：BO 名称和说明。
- `property_list`：由原始 `property_list` 转换为 `PropertyTerm`。
- `naming_sql_list`：同时支持从 `or_mapping_list[].naming_sql_list` 和 BO 顶层 `naming_sql_list` 收集。
- `tag`：从 BO 名称、描述、字段名、字段描述、字段类型、SQL 名称、SQL 描述、SQL 参数名和参数类型中构建。

这意味着 BO 的匹配不仅依赖对象名，也会受到字段和命名 SQL 的影响。例如用户需求中出现 `end date` 时，包含 `END_DATE` 参数的 BO 可以被初筛命中。

## Function 加载

`function_loader` 会把 `func` 和 `native_func` 下的函数统一拉平成 `FunctionRegistry`。

每个函数会包含：

- `resource_id`：按加载顺序生成，格式为 `func.0000`。
- `func_name`：函数调用名。
- `func_desc`：函数描述。
- `func_class`：函数所属类，来自外层 `class_name`。
- `param_list`：函数参数。
- `return_type`：原始返回类型；若缺失则使用默认 `basic void`。
- `tag`：从函数名、描述、类名、参数名、参数类型、返回类型中构建。

这让函数筛选可以同时利用自然语言描述和调用签名。例如 `mask customer call` 可以匹配到 `CustCallMask` 及其描述、类名和参数标签。

## 局部上下文可见性

局部上下文不是从静态资源文件读取，而是从当前请求携带的 `edsl_tree` 中解析。入口是 `load_visible_local_context_registry(edsl_tree, node_path)`。

计算规则如下：

1. 将传入的 `node_path` 标准化为 JSONPath；如果不是 `$` 开头，会补成 `$.xxx`。
2. 从当前路径向父路径回溯，得到候选路径列表。
3. 按从根到当前节点的顺序解析这些路径。
4. 只处理 `tree_node_type` 为 `parent` 或 `parent_list` 的祖先节点。
5. 从祖先节点上收集：
   - `local_context`，注册为 `$local$.<property_name>`，`property_type=local`
   - `lobal_context`，注册为 `$local$.<property_name>`，`property_type=local`
   - `iter_local_context`，注册为 `$iter$.<property_name>`，`property_type=iter`
6. 每个局部上下文记录 `source_path`，指向它在 `edsl_tree` 中的原始位置。

这种设计让子节点可以看到父节点定义的局部上下文，也能在列表节点下看到迭代上下文。对于插入位置，如果当前 node path 还不存在，路径回溯会找到已存在的祖先节点，从而仍能得到可见上下文。

需要注意的是，`LOCAL_CONTEXT_FIELDS` 中包含 `lobal_context`。从命名看它可能是为了兼容历史拼写或数据格式；如果不是兼容字段，应后续确认是否为拼写错误。

## Tag 构建与文本匹配

所有 registry 都会生成 `tag`，用于环境构建阶段的第一轮启发式筛选。`tag_utils` 的规则是：

- 将 `_`、`-`、`.` 替换为空格后分词。
- 支持英文驼峰、大写缩写、数字和中文连续片段。
- 第一个输入值会保留原文，并且不过滤停用词。
- 后续输入值如果不含空白，也会保留原文。
- 对常见英文停用词做过滤。
- 按出现顺序去重。

例如 `BB_BAK_TRANS_queryDataLoadData` 可以拆出 `BB`、`BAK`、`TRANS`、`query`、`Data`、`Load` 等标签。这个 tag 体系是当前资源召回的基础：loader 负责尽量把可解释字段转成标签，environment 负责根据需求词和节点信息评分。

## 环境筛选流程

资源加载完成后，`build_filtered_environment()` 会为当前节点构建 `FilteredEnvironment`。它的输入包括：

- 当前节点 `NodeDef`
- 用户自然语言需求 `user_query`
- `LoadedResource`
- 各类资源 top N 限制
- 可选的 `llm_resource_filter`

筛选分两阶段。

第一阶段是本地启发式打分：

1. 先通过 `registry.get_visible_local_context_registry(node_info.node_path)` 计算当前节点可见的局部上下文。
2. 从三类文本来源构建加权 token：
   - `user_requirement` 权重 3.0
   - `node_name` 权重 2.0
   - `description` 权重 1.0
3. 对 global context、local context、BO、function 分组分别打分。
4. 匹配得分分为：
   - 精确匹配：1.0
   - 子串匹配：0.5
   - 模糊匹配：0.3，`SequenceMatcher` 相似度不低于 0.8
5. 每组最多保留 `top_n * 5` 个候选，但不超过 30 个。

排序优先级是：

1. 总分更高。
2. 精确匹配数量更多。
3. 来自用户需求的得分更高。
4. 原始顺序更靠前。

第二阶段是可选 LLM 二次筛选：

1. 如果调用方传入了 `llm_resource_filter`，使用调用方提供的服务。
2. 如果没有传入，则尝试创建 `LLMResourceFilter`。
3. 如果 LLM 不可用、调用异常、返回无效资源 ID，系统都会回退到本地启发式排序结果。
4. LLM 只能从候选列表中选择资源 ID，不能发明新资源。
5. LLM 返回不足时，用本地候选补齐到对应 limit。

因此，当前设计具备一个明确的降级路径：LLM 可用时做语义重排；LLM 不可用时仍可通过 tag 匹配完成基础资源选择。

## 输出环境

`FilteredEnvironment` 同时保留资源 ID 和资源对象：

- `selected_global_context_ids` / `selected_global_contexts`
- `selected_local_context_ids` / `visible_local_context`
- `selected_bo_ids` / `selected_bos`
- `selected_function_ids` / `selected_functions`

后续 planner、validator、AST builder 和 renderer 可以使用这些资源来生成、验证和渲染 DSL。当前字段名 `visible_local_context` 实际存放的是筛选后的 local context，而不是全部可见 local context；如果后续需要同时保留“全部可见”和“已选择”，建议拆成两个字段以减少歧义。

## 测试覆盖

当前测试覆盖了资源管理的主要行为：

- 全局上下文递归展开、路径命名、类型继承、tag 构建。
- BO 中系统/自定义对象合并、字段和命名 SQL 收集。
- 函数中脚本函数和 native 函数合并、默认返回类型、tag 构建。
- 默认数据文件能被加载成 registry。
- 局部上下文能根据节点路径收集祖先节点上的 local 和 iter context。
- 环境构建能基于 tag 排序筛选资源。
- LLM 筛选可接管候选排序，并在异常或无效 ID 时回退。

建议在修改资源管理逻辑后至少运行：

```powershell
python -m unittest tests.test_resource_loader tests.test_registry_models tests.test_environment
```

## 扩展指南

### 新增资源字段

如果只是为现有资源类型增加字段，通常需要：

1. 在 `registry_models.py` 中扩展对应 Pydantic 模型。
2. 在对应 loader 中从原始 JSON 填充字段。
3. 如果该字段能帮助检索，在 `_build_*_tags()` 中加入 tag。
4. 在 `resource_filter._summarize_resource()` 中加入给 LLM 看的摘要字段。
5. 增加或更新单元测试，覆盖字段解析和筛选效果。

### 新增资源类型

如果要新增第五类资源，通常需要：

1. 新增 registry 模型。
2. 新增 loader，将 JSON payload 转成 registry。
3. 在 `ResourceLoader` 中增加数据读取、缓存和 `LoadedResource` 字段。
4. 在 `FilteredEnvironment` 中增加 selected ids 和 objects。
5. 在 `build_filtered_environment()` 中增加候选筛选逻辑。
6. 在 `LLMResourceFilter.RESOURCE_GROUPS`、候选摘要和 prompt 中加入新分组。
7. 增加端到端测试，确保本地筛选和 LLM 筛选都能处理新类型。

### 接入真实多项目资源

当前 `site_id` 和 `project_id` 只用于缓存 key，没有影响实际读取的数据。若要接入真实多项目资源，建议优先改造 `ResourceLoader.get_resource_data()`，使它成为唯一的数据源适配点。这样 loader、registry 模型和 environment 筛选逻辑都可以保持稳定。

## 当前注意点

1. `agent/edsl_gen_entry.py` 中调用的是 `resource_loader.load(...)`，但当前 `ResourceLoader` 暴露的方法名是 `load_resource(...)`。如果该入口会被执行，需要统一接口名。
2. `GenerateDSLRequest` 模型中字段名是 `node`，但 `edsl_gen_entry.py` 使用 `request.node_def`。这也是入口层需要对齐的问题。
3. `LOCAL_CONTEXT_FIELDS` 中的 `lobal_context` 命名需要确认。如果是历史兼容字段，应在代码中补充注释；如果是拼写错误，应改为预期字段并加回归测试。
4. `prompt.json` 当前显示为乱码，可能是编码问题。若 LLM 资源筛选依赖该 prompt，需要确认文件编码和 `PromptManager` 读取方式。
5. 全局 registry 缓存没有失效策略。若资源文件在进程运行期间会更新，需要补充刷新机制或版本化缓存 key。

## 一句话总结

当前资源管理方法是：把项目级 JSON 资源归一化为带 tag 的 registry，用节点路径动态补足局部上下文，再通过“本地加权匹配 + 可选 LLM 语义重排”生成当前节点的最小相关资源环境。
