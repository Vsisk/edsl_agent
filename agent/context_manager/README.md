# Context Manager 维护指南

## 快速认识

Context Manager 为 NamingSQL 选择链路构建可追溯、可裁剪的上下文。它从当前 EDSL 项目、资源注册表、logic area、OOTB 案例和站点知识中召回候选，再通过 LLM 完成受约束的重排和最终 Top-K 组织。

当前只实现 `chain_type="namingsql_selection"`。`BuildContextRequest` 中的其他 chain 值是未来扩展位；现在调用它们会得到 `UNSUPPORTED_CONTEXT_CHAIN`。

职责边界：

- `ContextManager` 负责加载、召回、重排、组织和追踪上下文。
- `NamingSqlSelector` 只是公开 facade：转换请求、调用 Context Manager、返回成功或稳定失败码。
- `ValueLogicGenerator` 决定当前生成是否需要 NamingSQL。
- `Planner` 只能消费 Selector 返回并经约束验证的 Top-K，不能回看完整 NamingSQL 列表。
- embedding 和 lexical 只负责召回；最终顺序由 LLM organizer 决定，代码不计算最终加权分数。

## 端到端链路

```mermaid
flowchart LR
    A[ValueLogicGenerator] -->|requires_naming_sql| B[NamingSqlSelector]
    B --> C[BuildContextRequest]
    C --> D[ContextManager]
    D --> E[Resolvers]
    E --> F[Embedding + Lexical Recall]
    F --> G[LLM Reranker]
    G --> H[ContextPackAssembler]
    H --> I[LLM Organizer]
    I --> J[Validated Top-K Response]
    J --> K[Planner]
```

运行时链路：

1. `ValueLogicGenerator.requires_naming_sql` 检查结构化信号和查询文本。
2. 默认 factory 使用本次请求的 `LoadedResource` 创建 request-scoped `ContextManager` 和 `NamingSqlSelector`。
3. Selector 把公开的 `NamingSqlSelectRequest` 转成内部 `BuildContextRequest`。
4. Context Manager 按固定顺序执行 resolver。
5. 资源候选先经过 embedding 语义召回和 lexical 精确补召回，再由 LLM reranker 选择受控候选。
6. Assembler 对 organizer 输入做预算和不透明 alias 映射；LLM organizer 产生最终 Top-K、需求提示和选择约束。
7. 代码校验 alias、数量、候选来源和约束，将结果还原成权威资源实体。
8. Planner 只看到受限摘要；`validate_naming_sql_plan` 阻止使用 Top-K 或约束集合之外的 NamingSQL。

## 目录与职责

```text
agent/context_manager/
  errors.py                 稳定错误码与 ContextBuildError
  models/                   请求、资产、候选、上下文块与 evidence 模型
  retrieval/                embedding、lexical、hybrid recall、LLM reranker
  resolvers/                各来源上下文的读取、归一化和召回
  renderers/                organizer 输入预算与安全渲染
  manager/                  固定顺序编排和最终上下文组装
  mock_data/                OOTB 与站点知识 JSONL 增强源
```

关键文件：

| 文件 | 主要职责 |
| --- | --- |
| `manager/context_manager.py` | 固定 resolver 顺序和链路编排 |
| `manager/assembler.py` | organizer 调用、alias 校验、Top-K 和约束组装 |
| `resolvers/resource.py` | 将 BO、NamingSQL、context、function 转为 `ContextAsset` |
| `resolvers/edsl_project.py` | 按 `json_path` 读取当前节点、亲属节点、local/iter context 和费用表结构 |
| `resolvers/logic_area.py` | 解析显式 logic area 或语义召回关联区域 |
| `resolvers/reference_cases.py` | 有界加载 OOTB、站点知识和历史案例 JSONL |
| `retrieval/embedding_client.py` | OpenAI-compatible embedding adapter；独立于现有 LLM 模块 |
| `retrieval/llm_reranker.py` | 使用现有 `agent.llm.LLMClient` 和 `PromptManager` 做严格 JSON 精排 |
| `renderers/naming_sql_context.py` | 在总预算内保留每个候选的决策事实并移除 SQL 正文 |

## 核心数据契约

### `NamingSqlSelectRequest`

公开 Selector 请求，定义在 `agent/naming_sql_selector/models.py`：

```python
NamingSqlSelectRequest(
    site_id="THAILAND",
    project_id="billing_v3",
    query="查询当前账期费用",
    node=current_node,
    json_path="$.mapping_content.children[2]",
    target_bo_name="BB_BILL_CHARGE",       # 可选
    parent_bo_hint=None,                    # 可选
    target_logic_area_id_list=[],           # 可选
    top_k=5,                                # 1..20
    debug=False,
)
```

### `BuildContextRequest`

内部统一入口。除公开字段外，还包含：

- `chain_type`：默认 `namingsql_selection`；当前只支持这个值。
- `max_context_items`：控制进入 organizer 前的上下文项目预算。
- `top_k`：最终候选数量上限。

### `ContextAsset`

所有可检索来源先归一化为资产：

- `asset_id`：稳定标识，必须映射到已加载资源或已加载案例。
- `asset_type`：如 `bo`、`bo_field`、`naming_sql`、`logic_area`、`site_knowledge`。
- `scope`：global、site、project、logic_area、node 或 task。
- `content`：权威结构化事实。
- `index_text`：按资产类型构造的语义文本，不能只是原始 JSON dump。
- `metadata`：召回诊断信息；embedding 相似度可以保留在这里，但不能成为代码侧最终排序。

### `NamingSqlSelectResponse`

成功响应包含：

- `candidates`：已排序并带连续 `rank` 的最终 Top-K。
- `context_requirements_hint`：Planner 后续参数和上下文需求提示。
- `selection_constraints`：允许的 BO、NamingSQL ID 和候选数量边界。
- `evidence_trace`：resolver、reranker 和 organizer 的证据链。
- `prompt_view`：只在 `debug=True` 时返回。

失败响应满足 `success=False`、候选为空，并仅暴露稳定 `failure_reason`。

## Resolver 执行顺序

`ContextManager.build_context` 的顺序是稳定契约：

1. `GlobalContextResolver`
   - 读取 `agent_rules/GLOBAL.md`。
   - 读取 `agent_rules/chains/namingsql_selection.md`。
2. `EdslProjectContextResolver`
   - 从 `LoadedResource.edsl_tree` 精确解析 `json_path`。
   - 提取当前、父、祖先、兄弟节点，local/iter context 和 data source。
3. `LogicAreaContextResolver`
   - 优先使用节点引用，其次请求指定 ID，最后使用语义召回。
4. `ResourceContextResolver`
   - 读取 BO、BO field、NamingSQL、global/local context 和 function。
5. `OOTBContextResolver`
   - 读取 `mock_data/ootb_cases.jsonl`；文件缺失是非致命增强源缺失。
6. `SiteKnowledgeContextResolver`
   - 按 `site_id` 和 `project_id` 过滤 `mock_data/site_knowledge_cases.jsonl`。
7. `ContextPackAssembler`
   - 合并 evidence、执行预算、调用 organizer 并校验最终 Top-K。

所有 resolver 都应输出 `ContextEvidenceItem`。增加新 resolver 时，不要只返回候选而丢失来源、动作和判断依据。

## 召回、重排与组织

### Semantic recall

`SemanticRetriever` 使用 `EmbeddingClient.embed_texts` 计算余弦相似度。它验证向量数量、维度、有限值，并用数值稳定的归一化处理极大或极小向量。相似度只写入资产副本的 metadata。

### Lexical supplementation

`LexicalRetriever` 针对资产 ID、名称、字段和参数做精确补召回。它不计算跨特征加权总分。

### Hybrid recall

`HybridRetriever` 保持 semantic-first 顺序，再追加未出现的 lexical 命中，并按 `asset_id` 稳定去重。

### LLM reranker

Reranker 使用不透明 alias，模型不能看到或创造权威资源 ID。输出必须是严格 JSON；未知、重复或冲突引用会得到 `INVALID_LLM_OUTPUT`。

### LLM organizer

Organizer 只从已经展示的候选 alias 中产生最终 Top-K。Assembler 负责：

- 在 alias 创建前执行总预算；
- 确保每个可选候选仍保留 BO、名称、参数和返回摘要等决策事实；
- 将 hint、evidence 和 constraints 中的 alias 还原为权威 ID；
- 验证最终数量、约束子集和连续 rank；
- 不允许 SQL 命令正文进入 prompt。

## 配置与最小接入

必需环境变量：

```dotenv
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://your-compatible-endpoint/v1
OPENAI_MODEL=qwen3.5-35b-a3b
OPENAI_EMBEDDING_MODEL=your-embedding-model
```

LLM 调用复用现有 `agent.llm.LLMClient`、`PromptManager` 和 `prompt.json`。本模块只新增 embedding adapter，不维护第二套 LLM transport。

生产集成通常不需要手工组装依赖。`ValueLogicGenerator` 默认按当前资源快照创建 Selector：

```python
from agent.context_manager import ContextManager
from agent.naming_sql_selector import NamingSqlSelector
from agent.value_logic_generator import ValueLogicGenerator


def selector_factory(loaded_resource):
    return NamingSqlSelector(ContextManager(loaded_resource))
```

测试或自定义部署可注入 factory：

```python
generator = ValueLogicGenerator(
    naming_sql_selector_factory=selector_factory,
)
```

`ContextManager` 是 request-scoped 的，因为它持有当前 `LoadedResource`，其中包含本次请求的 EDSL tree。不要把绑定旧项目快照的 manager 长期复用到其他项目请求。

## 扩展指南

### 新增 Resolver

1. 在 `agent/context_manager/resolvers/` 新建单一职责模块。
2. 输入只使用 `BuildContextRequest`、`LoadedResource` 和前序结构化 block。
3. 把可检索内容转成 `ContextAsset`，使用稳定 ID 和专用 `index_text`。
4. 对外部或模型返回的 ID 做 canonical map 校验；不要信任返回对象中的 content。
5. 输出候选和 `evidence_trace`。
6. 在 `ContextManager` 中明确插入执行顺序，并为顺序和参数写测试。
7. 如需进入 organizer，更新 renderer 的受控字段和总预算测试。

### 新增资产类型

1. 扩展 `ContextAsset.asset_type` literal。
2. 在对应 builder 中生成稳定 ID、权威 content 和语义化 `index_text`。
3. 更新 reranker/renderer 白名单式映射。
4. 添加“无原始 JSON dump、无权威事实编造、输入不被修改”的测试。

### 新增 Chain

模型允许未来 chain 值，但运行时尚未实现。新增 chain 时至少需要：

1. 独立规则文件 `agent_rules/chains/<chain>.md`；
2. chain-specific resolver/assembler 或显式复用策略；
3. 独立输出契约与调用方；
4. `ContextManager.build_context` 分派；
5. 不支持链路的失败和端到端测试。

不要仅删除 `UNSUPPORTED_CONTEXT_CHAIN` 检查就宣称 chain 已可用。

## 测试

核心测试：

```powershell
python -m pytest tests/test_context_models.py -q
python -m pytest tests/test_context_retrieval.py tests/test_llm_reranker_contract.py -q
python -m pytest tests/test_context_resolvers.py -q
python -m pytest tests/test_context_manager_namingsql.py -q
python -m pytest tests/test_namingsql_selector_context_request.py -q
python -m pytest tests/test_value_logic_generator.py tests/test_llm_planner.py tests/test_naming_sql_plan_validator.py -q
```

全量验证：

```powershell
python -m pytest -q
```

单元测试通过依赖注入使用 fake embedding、fake LLM、fake resolver 和 capturing manager，不需要网络。Fake LLM 应返回与生产相同的严格 JSON 结构；fake embedding 应保持输入与向量一一对应。

## 常见失败与排查

| 错误码 | 含义 | 优先检查 |
| --- | --- | --- |
| `AI_CONFIGURATION_REQUIRED` | LLM 或 embedding 配置不可用 | API key、base URL、两个模型名 |
| `EMBEDDING_FAILED` | embedding 请求或向量形状无效 | endpoint、模型兼容性、向量维度与有限值 |
| `LLM_RERANK_FAILED` | reranker 调用或 prompt 渲染失败 | `prompt.json`、LLM 可用性、候选预算 |
| `LLM_ORGANIZER_FAILED` | organizer 调用或渲染失败 | organizer prompt、模型 JSON 能力 |
| `INVALID_LLM_OUTPUT` | JSON schema、alias 或约束校验失败 | fake/真实响应字段、未知或重复引用 |
| `RULE_FILE_MISSING` | 全局或 chain 规则文件缺失/为空 | `agent_rules/` 是否随部署发布 |
| `EDSL_NODE_NOT_FOUND` | `json_path` 无法定位项目节点 | 路径是否属于当前 `LoadedResource.edsl_tree` |
| `UNSUPPORTED_CONTEXT_CHAIN` | 请求了尚未实现的 chain | `chain_type` 应为 `namingsql_selection` |
| `NO_NAMING_SQL_CANDIDATES` | 没有可展示和组织的合法 NamingSQL | 资源加载、BO 范围、召回文本和过滤条件 |

系统对必需 AI 阶段采用 fail-closed：不会在 embedding 或 LLM 失败后悄悄改用确定性最终排名。OOTB/站点案例文件属于增强源，缺失时会记录 evidence 并继续；权威资源、规则或项目节点缺失则可能终止链路。

## 安全边界

- LLM 只能选择 prompt 中存在的不透明 alias。
- 所有 alias 都必须映射回 canonical asset；返回对象的 content 不可信。
- Prompt 不包含 SQL 命令正文，也不暴露内部 candidate ID。
- 查询、上下文、候选数、单字段和 JSONL 读取都有明确预算。
- JSONL 解析和语义遍历有字节、记录、深度和项目数限制。
- Selector 只对登记的 `ContextBuildError` 返回稳定错误码；未知异常继续抛出。
- Planner summary 不包含 evidence payload 或内部 asset ID。
- Planner 的 fetch 必须属于 Top-K 和 `selection_constraints` 允许的子集，参数名必须存在于候选定义中。

## 维护检查清单

提交 Context Manager 变更前确认：

- [ ] 没有在 Selector 或 Planner 中加入资源搜索逻辑。
- [ ] 新候选来自已加载资源或已加载案例，且有 evidence trace。
- [ ] `index_text` 是类型专用语义文本，不是 JSON dump。
- [ ] embedding/lexical 没有变成代码侧最终加权排序。
- [ ] LLM 输出使用严格 JSON，并验证未知、重复和越界引用。
- [ ] Organizer 看不到 SQL 正文和 canonical candidate ID。
- [ ] `max_context_items`、Top-K 和 prompt 总预算有边界测试。
- [ ] `debug=False` 不返回 prompt view。
- [ ] Planner 不能使用 Top-K 或 constraints 之外的 NamingSQL。
- [ ] fake client 测试和普通非 NamingSQL 回归测试均通过。
- [ ] 新规则和 mock 数据路径会随实际部署方式一起发布。
