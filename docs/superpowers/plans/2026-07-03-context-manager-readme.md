# Context Manager README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an accurate maintainer guide for `agent/context_manager` and link it from the repository README.

**Architecture:** The module README documents the implemented NamingSQL context pipeline from public entry points down to resolvers, retrieval, organizer validation, and planner consumption. It derives every path, symbol, environment variable, and failure code from current source rather than restating the earlier proposal.

**Tech Stack:** Markdown, Python source inspection, pytest, ripgrep.

---

### Task 1: Verify Documentation Facts

**Files:**
- Read: `agent/context_manager/**/*.py`
- Read: `agent/naming_sql_selector/*.py`
- Read: `agent/value_logic_generator.py`
- Read: `agent/planner/llm_planner.py`
- Read: `.env.example`
- Read: `agent_rules/*.md`

- [ ] **Step 1: Inventory public symbols and flow**

Run:

```powershell
rg -n "class (ContextManager|ContextPackAssembler|BuildContextRequest|NamingSqlSelectRequest|NamingSqlSelectResponse)|def build_context|def select" agent/context_manager agent/naming_sql_selector
rg -n "requires_naming_sql|naming_sql_selector_factory|naming_sql_selection" agent/value_logic_generator.py agent/planner/llm_planner.py
```

Expected: current request, selector, manager, assembler, generator, and planner integration points are listed.

- [ ] **Step 2: Inventory configuration and failures**

Run:

```powershell
rg -n "OPENAI_|^[A-Z_]+ =" .env.example agent/llm/config.py agent/context_manager/errors.py
```

Expected: the four documented OpenAI variables and stable Context Manager error codes are visible.

- [ ] **Step 3: Inventory tests and extension seams**

Run:

```powershell
rg -n "class .*Resolver|class .*Retriever|class EmbeddingClient|class LLMReranker" agent/context_manager
rg -n "Fake|ContextManager|LLMReranker|Resolver" tests/test_context_*.py tests/test_llm_reranker_contract.py
```

Expected: resolver, retrieval, fake-client, and focused test locations are visible.

### Task 2: Write the Maintainer Guide

**Files:**
- Create: `agent/context_manager/README.md`
- Modify: `README.md`

- [ ] **Step 1: Create the module README**

Write a Chinese maintainer guide with these exact top-level sections:

```markdown
# Context Manager 维护指南
## 快速认识
## 端到端链路
## 目录与职责
## 核心数据契约
## Resolver 执行顺序
## 召回、重排与组织
## 配置与最小接入
## 扩展指南
## 测试
## 常见失败与排查
## 安全边界
## 维护检查清单
```

The guide must state that only `namingsql_selection` is implemented, final ordering belongs to the LLM organizer, candidates must map to loaded resources, the selector is a facade, and the planner sees only validated Top-K candidates. Include one compact Mermaid flow diagram, one request-scoped factory example based on current code, focused test commands, and a stable failure-code table.

- [ ] **Step 2: Add the root README link**

Add directly after the existing overview:

```markdown
完整的架构、扩展与排错说明见 [Context Manager 维护指南](agent/context_manager/README.md)。
```

- [ ] **Step 3: Check local links and stale identifiers**

Run:

```powershell
rg -n "NamingSqlSelectionResult|NamingSqlSelectionRequest|NamingSqlProfileBuilder|deterministic relevance score" agent/context_manager/README.md README.md
Test-Path agent/context_manager/README.md
Test-Path agent_rules/GLOBAL.md
Test-Path agent_rules/chains/namingsql_selection.md
```

Expected: stale-identifier search returns no matches and all path checks return `True`.

### Task 3: Reader-Test and Verify

**Files:**
- Modify if needed: `agent/context_manager/README.md`

- [ ] **Step 1: Verify code examples and documentation assertions**

Run:

```powershell
python -m pytest tests/test_context_manager_namingsql.py tests/test_namingsql_selector_context_request.py tests/test_value_logic_generator.py tests/test_llm_planner.py -q
git diff --check
```

Expected: tests pass and diff check emits no errors.

- [ ] **Step 2: Test with a fresh reader**

Give a fresh reader only `agent/context_manager/README.md` and ask:

```text
1. NamingSQL Top-K 的最终顺序由谁决定？
2. 新增 Resolver 要改哪些位置？
3. 缺少 embedding 配置时系统如何处理？
4. Planner 能否使用 Top-K 外的 NamingSQL？
5. 如何用 fake client 运行相关测试？
```

Expected: all five answers are unambiguous and match current code.

- [ ] **Step 3: Commit the documentation**

```powershell
git add agent/context_manager/README.md README.md
git commit -m "docs: add context manager maintainer guide"
```
