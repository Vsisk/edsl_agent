# 全局表达式技巧与列表作用域 实现计划

> **给 Claude：** 必需工作流：使用 superpowers:executing-plans 逐任务实现此计划，并在每个行为增量中遵循 `$test-driven-development`。

**目标：** 让列表内字段在 spec、资源环境、TypedContext、planner 和本地校验链路中可靠使用带类型的 `$iter$`，并通过一个系统内置 Markdown 技巧库按需提供列表与日期表达式方法。

**相关设计文档：** `docs/superpowers/specs/2026-07-16-expression-skill-list-scope-design.md`

**架构：** 新建 `agent/expression_generation/expression_spec.py`，把 ExpressionSpec 模型、全局 Markdown 技巧解析和确定性召回集中为一个深模块。`ValueLogicGenerator` 在普通资源筛选后无条件合并结构性 `$iter$`；TypedContext 注册其 BO 类型与字段。ContextPack 提供动态 list-scope 事实，planner 分别接收结构化 scope 和技巧 JSON，parser/validator 完成本地闭环。

**技术栈：** Python 3.14、dataclass/Pydantic 2、现有 jsonpath-ng、markdown-it-py、pytest、现有 ContextPack 和表达式类型系统。

**范围 / 非范围：** 本次实现全局 expression skill、列表 `$iter$` 和 Date 年/月技巧。项目级 `dev_skill` 保持不变；不生成 `parent_list.data_source`，不新增变量重名校验，不引入额外 LLM 调用。

---

## Phase #1: 全局技巧库与结构化 ExpressionSpec

### Task #1: Markdown 技巧库解析与确定性召回

**状态：** Desinged

**文件：**
- 创建：`agent/expression_generation/resources/expression_skill.md`
- 创建：`agent/expression_generation/expression_spec.py`
- 创建：`tests/test_expression_spec.py`
- 修改：`agent/value_logic_generator.py`
- 功能：解析全局技巧章节，并依据 list scope、年、月语义召回。
- 实现说明：定义 `ExpressionScopeContext`、`ExpressionSkillInstruction`、`ExpressionSpec`、`ExpressionSkillLibrary` 和 `ExpressionSpecGenerator`。Markdown 每个 H2 章节包含稳定 `skill_id` 与 `triggers` 元数据；list 技巧由结构信号触发，日期技巧由 query、节点名称和注释触发。`nl` 始终保持原始用户需求。
- 预期验证结果：列表内字段即使 query 不提“列表”也召回 list 技巧；非列表不召回；年/月分别召回对应方法；技巧文本不进入 `nl`；缺失文件明确失败。

验证命令：

```powershell
python -m pytest tests/test_expression_spec.py -v
```

## Phase #2: 结构性 `$iter$` 与 TypedContext

### Task #2: 资源过滤后保留 `$iter$`

**状态：** Desinged

**文件：**
- 修改：`agent/environment/environment.py`
- 修改：`agent/value_logic_generator.py`
- 修改：`tests/test_environment.py`
- 修改：`tests/test_value_logic_generator.py`
- 功能：确保 `$iter$` 不因语义筛选为空或不匹配而丢失。
- 实现说明：增加公开的结构上下文合并函数，按当前 `node_path` 从 `LoadedResource` 读取可见资源，只合并精确 `$iter$`，按 `context_name` 去重，并同步 `selected_local_context_ids`。在 ValueLogicGenerator 两条过滤路径收敛后、TypedContext 构建前调用。
- 预期验证结果：无 target、非匹配 target 和 legacy filter 均保留 `$iter$`；非列表节点不新增资源；显式 `$local$` 仍按原规则筛选。

验证命令：

```powershell
python -m pytest tests/test_environment.py tests/test_value_logic_generator.py -k "structural_iter or typed_context" -v
```

### Task #3: `$iter$` TypeRef 和 BO 字段展开

**状态：** Desinged

**文件：**
- 修改：`agent/expression_generation/typed_context.py`
- 修改：`tests/test_typed_expression_context.py`
- 功能：把 `$iter$` 注册为可展开的 typed root。
- 实现说明：扩展 BO 注册来源，扫描 `visible_local_context` 中的返回类型；若为 BO 或 List<BO>，从权威 `loaded_resource.bo_registry` 注册 BO TypeDef。沿用 `_append_context_root` 输出 `$iter$` root 与 `$iter$.FIELD` fields。
- 预期验证结果：未被普通 BO 选择命中的 iterator BO 仍能展开字段；logic/extattr/basic 行为保持现状；item budget 继续生效。

验证命令：

```powershell
python -m pytest tests/test_typed_expression_context.py -v
```

## Phase #3: 本地表达式闭环

### Task #4: parser 与 validator 支持裸 `$iter$` 和字段链

**状态：** Desinged

**文件：**
- 修改：`agent/expression_generation/edsl_expression_parser.py`
- 修改：`agent/expression_generation/ast/validator.py`
- 修改：`tests/test_edsl_expression_parser.py`
- 修改：`tests/test_expression_validator.py`
- 功能：把 `$iter$` 作为 context root 解析和推断，而不是普通变量。
- 实现说明：parser fallback root 集合加入 `$iter$`；validator 的 registry path 判定接受精确 `$iter$`，context root 最长匹配循环允许单段根。未知 `$iter$` 必须返回 `context path not found`。
- 预期验证结果：`$iter$`、`$iter$.ID` 能构建并推断类型；无 root 时校验失败；已有 `$ctx$`/`$local$` 不回归。

验证命令：

```powershell
python -m pytest tests/test_edsl_expression_parser.py tests/test_expression_validator.py -v
```

## Phase #4: ContextPack 动态列表事实

### Task #5: current-tree list scope metadata 与权威 iterator item

**状态：** Desinged

**文件：**
- 修改：`agent/context_pack/providers/current_tree.py`
- 修改：`agent/context_pack/prompt_renderer.py`
- 修改：`tests/test_context_pack_current_tree.py`
- 修改：`tests/test_context_pack_prompt_renderer.py`
- 功能：让 spec/planner 在 ContextPack 中看到当前节点处于列表体和 `$iter$` 的实际类型。
- 实现说明：provider 使用 loader 结果构造 metadata，并为 `$iter$` 创建确定性的 authoritative structural item；搜索时为结构 item 预留预算。renderer 仅投影 current_tree 的白名单 metadata 字段，保持全局字符预算和不泄露整树。
- 预期验证结果：列表内节点包含 `inside_parent_list=true`、parent path、iter return type 和 iterator item；非列表 metadata 为 false 且无 item；renderer 输出稳定有界。

验证命令：

```powershell
python -m pytest tests/test_context_pack_current_tree.py tests/test_context_pack_prompt_renderer.py -v
```

## Phase #5: spec 与 planner 使用技巧

### Task #6: planner 接收 ExpressionSpec scope/skills

**状态：** Desinged

**文件：**
- 修改：`agent/planner/simple_expression_planner.py`
- 修改：`agent/planner/llm_planner.py`
- 修改：`agent/value_logic_generator.py`
- 修改：`prompt.json`
- 修改：`tests/test_simple_expression_planner.py`
- 修改：`tests/test_llm_planner.py`
- 修改：`tests/test_planner_prompt.py`
- 修改：相关 FakePlanner 签名/断言
- 功能：simple、legacy 和 repair planner 获得相同的列表 scope 与技巧说明。
- 实现说明：planner `plan` 增加可选 `expression_spec`；使用有界 serializer 生成 `expression_scope_json` 和 `expression_skills_json`。三个 prompt 明确 `$iter$` 最近层语义、字段必须来自 TypedContext、外层值使用 `$local$`、技巧为 normative system knowledge。repair 复用原始 spec。
- 预期验证结果：三个 prompt 都包含 list scope 和 `$iter$.FIELD` 规则；日期技巧精确出现；普通请求传空 scope/skills；资源 JSON 不被技巧污染。

验证命令：

```powershell
python -m pytest tests/test_simple_expression_planner.py tests/test_llm_planner.py tests/test_planner_prompt.py tests/test_value_logic_generator.py -v
```

## Phase #6: 端到端与完成前验证

### Task #7: `$iter$.FIELD` 端到端生成

**状态：** Desinged

**文件：**
- 修改：`tests/test_simple_expression_end_to_end.py`
- 修改：必要的集成 fixture
- 功能：从列表树、结构性 `$iter$`、TypedContext、SimplePlan 到 AST validator 完成闭环。
- 实现说明：使用真实 loader/type registry/parser/validator，planner test double 返回 `$iter$.ID`，断言最终表达式、结果 return type 和 debug typed root。
- 预期验证结果：端到端表达式为 `$iter$.ID` 且静态类型正确；同样请求移到列表外时无法使用 iterator。

验证命令：

```powershell
python -m pytest tests/test_simple_expression_end_to_end.py tests/test_edsl_gen_entry.py -v
```

### Task #8: `$verification-before-completion` 验证门

**状态：** Desinged

**文件：**
- 验证：全部修改文件与完整测试套件
- 功能：仅凭新鲜完整证据声明完成。
- 实现说明：逐条核对设计 Acceptance Criteria；搜索是否仍存在 planner 不接收 expression_spec 的调用；检查 diff 空白；运行相关测试集合和完整 pytest。提交后合并到 main，并在合并结果上重新运行完整 pytest，读取 exit code 和失败数后才清理 worktree。
- 预期验证结果：`git diff --check` exit 0；相关测试 0 failures；完整 `python -m pytest -q` exit 0；main 合并后同样 0 failures。

验证命令：

```powershell
git diff --check
rg -n -S "\.plan\(" agent tests
python -m pytest tests/test_expression_spec.py tests/test_environment.py tests/test_typed_expression_context.py tests/test_edsl_expression_parser.py tests/test_expression_validator.py tests/test_context_pack_current_tree.py tests/test_context_pack_prompt_renderer.py tests/test_simple_expression_planner.py tests/test_llm_planner.py tests/test_planner_prompt.py tests/test_simple_expression_end_to_end.py tests/test_value_logic_generator.py -q
python -m pytest -q
```
