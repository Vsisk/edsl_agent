# ContextPackManager Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the unified `ContextPackManager` core and the `dev_skill`, `current_tree`, and `ootb_edsl` providers with strict resource gating, canonical local retrieval, deterministic fallback, evidence, conflicts, and budgets.

**Architecture:** Add an isolated `agent.context_pack` package without changing existing generation or NamingSQL callers. The manager dispatches only requested providers; providers return canonical `ContextItem` values; the builder applies authority-aware conflict detection and bounded assembly. Later plans adapt business callers and migrate NamingSQL.

**Tech Stack:** Python 3.12, Pydantic 2, pytest, markdown-it-py 4.2.0, existing `LoadedResource`, `load_visible_local_context_registry`, and injectable embedding clients.

---

## Scope and file map

This phase does not modify `ValueLogicGenerator`, planners, operation orchestration, `NamingSqlSelector`, or `agent.context_manager`.

```text
requirements-context-pack.txt
agent/context_pack/
  __init__.py
  errors.py
  project_context.py
  registry.py
  manager.py
  builder.py
  models/{__init__,request,pack,search}.py
  search/{__init__,rank_fusion,local_resource_search,cache}.py
  indexing/{__init__,markdown_skill,edsl_tree}.py
  providers/{__init__,dev_skill,current_tree,ootb_edsl}.py
tests/test_context_pack_*.py
agent/context_pack/README.md
```

### Task 1: Pin Markdown AST parsing

**Files:**
- Create: `requirements-context-pack.txt`

- [ ] Add exactly `markdown-it-py==4.2.0`.
- [ ] Run `uv pip install --python .venv\Scripts\python.exe -r requirements-context-pack.txt`.
- [ ] Run `.venv\Scripts\python.exe -c "import markdown_it; assert markdown_it.__version__ == '4.2.0'"`; expect exit 0.
- [ ] Commit with `git add requirements-context-pack.txt && git commit -m "build: pin context pack markdown parser"`.

### Task 2: Define strict request, search, and pack contracts

**Files:**
- Create: `agent/context_pack/errors.py`
- Create: `agent/context_pack/models/request.py`
- Create: `agent/context_pack/models/pack.py`
- Create: `agent/context_pack/models/search.py`
- Create: `agent/context_pack/models/__init__.py`
- Test: `tests/test_context_pack_models.py`

- [ ] Write failing tests for the three-field request, empty values, unknown resources, duplicate resource removal, extra-field rejection, independent defaults, mandatory locators, and enum serialization.

```python
def test_request_contract():
    request = ContextPackRequest(
        node={"node_id": "n1"}, query="生成客户姓名",
        resource_names=["dev_skill", "current_tree", "dev_skill"],
    )
    assert request.resource_names == [ResourceName.DEV_SKILL, ResourceName.CURRENT_TREE]
    assert set(request.model_dump()) == {"node", "query", "resource_names"}
```

- [ ] Run `python -m pytest tests/test_context_pack_models.py -q`; expect import failure.
- [ ] Define `ResourceName(dev_skill, ootb_edsl, current_tree, namingsql)`, `PackStatus`, `SectionStatus`, and `Authority`.
- [ ] Implement `ContextPackRequest` with `ConfigDict(extra="forbid")`; strip query, reject empty node/query/resources, and deduplicate resources in first-occurrence order.
- [ ] Define `SourceLocator`, `RetrievalEvidence`, `ContextFact`, `ContextItem`, `BudgetUsage`, `ContextSection`, `ContextConflict`, `ContextWarning`, `ContextTraceItem`, and `ContextPack`.
- [ ] Define `SearchDocument`, `SearchHit`, `SearchResult`, and `SearchFilters`. Every document has stable ID, source ID, locator, content hash, authority, content, summary, search text, and facts.
- [ ] Run the test again; expect all tests pass.
- [ ] Commit with `git add agent/context_pack/errors.py agent/context_pack/models tests/test_context_pack_models.py && git commit -m "feat: define context pack contracts"`.

### Task 3: Add ProjectContext, registry, and strict dispatch

**Files:**
- Create: `agent/context_pack/project_context.py`
- Create: `agent/context_pack/registry.py`
- Create: `agent/context_pack/manager.py`
- Test: `tests/test_context_pack_registry_manager.py`

- [ ] Write failing tests using capturing providers. Assert only requested providers run, duplicate registration fails, missing registration is explicit, and output order is `current_tree, namingsql, dev_skill, ootb_edsl`.

```python
@dataclass(frozen=True, slots=True)
class ProjectContext:
    current_tree: dict[str, Any] | None = None
    ootb_tree: dict[str, Any] | None = None
    dev_skill_path: Path | None = None
    loaded_resource: LoadedResource | None = None
    source_versions: Mapping[str, str] = field(default_factory=dict)
```

- [ ] Run `python -m pytest tests/test_context_pack_registry_manager.py -q`; expect missing imports.
- [ ] Implement `ProjectContext`, `RecallProfile(max_items, max_chars)`, provider protocol, and duplicate-safe `SourceRegistry`.
- [ ] Implement manager dispatch. Convert only `ContextProviderError` to sanitized error sections; allow unexpected exceptions to surface.
- [ ] Run tests; expect all pass.
- [ ] Commit with `git add agent/context_pack/project_context.py agent/context_pack/registry.py agent/context_pack/manager.py tests/test_context_pack_registry_manager.py && git commit -m "feat: add context provider dispatch"`.

### Task 4: Implement deterministic local search and cache

**Files:**
- Create: `agent/context_pack/search/rank_fusion.py`
- Create: `agent/context_pack/search/local_resource_search.py`
- Create: `agent/context_pack/search/cache.py`
- Create: `agent/context_pack/search/__init__.py`
- Test: `tests/test_context_pack_search.py`

- [ ] Write failing tests for pinned exact hits, stable ties, embedding degradation, unknown sources, path traversal, stale hashes, and versioned LRU keys.
- [ ] Run `python -m pytest tests/test_context_pack_search.py -q`; expect missing imports.
- [ ] Normalize Unicode by lowercasing and collapsing whitespace. Fuse lexical and semantic ranks only inside one source:

```python
scores[item_id] += 1.0 / (60 + rank)
```

- [ ] Sort by fused score descending, minimum source rank, then original document order; exact ID/name/path hits remain pinned.
- [ ] Implement `search(source_id, query, filters, limit)`. Embedding failure preserves exact/lexical hits and marks the result degraded.
- [ ] Implement `read_slice`: require a registered root, reject traversal, read the locator range, compute SHA-256, and reject stale content.
- [ ] Implement immutable-tuple LRU keys `(source_id, source_version, parser_version, embedding_model_version)`.
- [ ] Run tests; expect all pass.
- [ ] Commit with `git add agent/context_pack/search agent/context_pack/models/search.py tests/test_context_pack_search.py && git commit -m "feat: add bounded local context search"`.

### Task 5: Parse and retrieve development skill recipes

**Files:**
- Create: `agent/context_pack/indexing/markdown_skill.py`
- Create: `agent/context_pack/providers/dev_skill.py`
- Create: `agent/context_pack/indexing/__init__.py`
- Create: `agent/context_pack/providers/__init__.py`
- Test: `tests/test_context_pack_markdown_skill.py`

- [ ] Write failing tests using headings `客户信息 / 客户完整姓名 / 规则 / 示例`. Assert one recipe includes title, firstName, middleName, lastName, null filtering and concatenation; inherits parents; preserves code fences; and has a stable locator/hash. Test long splitting and missing-file status.
- [ ] Run `python -m pytest tests/test_context_pack_markdown_skill.py -q`; expect missing imports.
- [ ] Parse with `MarkdownIt("commonmark").parse(text)`. Use heading tokens and line maps. H2/H3 leaf sections are roots and include subordinate H4+ blocks.
- [ ] Generate IDs and hashes:

```python
item_id = "skill:" + sha256(f"{source_id}|{'/'.join(heading_path)}".encode()).hexdigest()[:20]
content_hash = sha256(slice_text.encode("utf-8")).hexdigest()
```

- [ ] Implement `DevSkillProvider`: missing file returns unavailable; otherwise cache by hash, search query plus node semantics, canonical-read 1–3 hits, and return normative `knowledge_recipe` items.
- [ ] Run tests; expect all pass.
- [ ] Commit with `git add agent/context_pack/indexing agent/context_pack/providers/dev_skill.py agent/context_pack/providers/__init__.py tests/test_context_pack_markdown_skill.py && git commit -m "feat: retrieve development skill recipes"`.

### Task 6: Build the shared EDSL index

**Files:**
- Create: `agent/context_pack/indexing/edsl_tree.py`
- Test: `tests/test_context_pack_edsl_index.py`

- [ ] Write failing tests with a parent list, simple leaf, table detail/group/summary fields, local/iter declarations, and duplicate names at different paths.
- [ ] Assert stable IDs, JSONPath/XMLPath, parent/ancestors, type, field role, search text, distinct duplicate paths, and bounded snippets.
- [ ] Run `python -m pytest tests/test_context_pack_edsl_index.py -q`; expect missing builder.
- [ ] Traverse `mapping_content` when present, otherwise root, following children in source order. Emit node, field, local, and iter entries with bounded content.
- [ ] Run tests; expect all pass.
- [ ] Commit with `git add agent/context_pack/indexing/edsl_tree.py tests/test_context_pack_edsl_index.py && git commit -m "feat: index local EDSL context"`.

### Task 7: Implement CurrentTreeProvider

**Files:**
- Create: `agent/context_pack/providers/current_tree.py`
- Test: `tests/test_context_pack_current_tree.py`

- [ ] Write failing tests for exact node-ID location, relevant fields, visible local/iter only, BO-field exclusion, unmapped current node, and tree immutability.
- [ ] Run `python -m pytest tests/test_context_pack_current_tree.py -q`; expect missing provider.
- [ ] Locate exact `node_id`; verify optional `node_path`. Build the index lazily only inside `retrieve`.
- [ ] Enforce visibility:

```python
visible = load_visible_local_context_registry(project_context.current_tree, current_json_path)
allowed_paths = {item.source_path for item in visible}
```

- [ ] Search query plus node name/annotation/type, re-resolve winning paths, and return 3–10 authoritative items. Never access BO registry fields.
- [ ] Run tests; expect all pass.
- [ ] Commit with `git add agent/context_pack/providers/current_tree.py tests/test_context_pack_current_tree.py && git commit -m "feat: retrieve current tree context"`.

### Task 8: Implement OotbEdslProvider

**Files:**
- Create: `agent/context_pack/providers/ootb_edsl.py`
- Test: `tests/test_context_pack_ootb.py`

- [ ] Write failing tests for missing source, compatible-type preference, incompatible exclusion, ancestor path, snippet bounds, canonical re-resolution, reference authority, and immutability.
- [ ] Run `python -m pytest tests/test_context_pack_ootb.py -q`; expect missing provider.
- [ ] Cache index by OOTB version/hash; hard-filter by request-node type and structure; never silently widen to incompatible types.
- [ ] Search name, annotation, semi-structured text, and structure. Re-resolve 1–3 hits and copy bounded reference snippets with truncation evidence.
- [ ] Run tests; expect all pass.
- [ ] Commit with `git add agent/context_pack/providers/ootb_edsl.py tests/test_context_pack_ootb.py && git commit -m "feat: retrieve bounded OOTB references"`.

### Task 9: Assemble conflicts, budgets, and statuses

**Files:**
- Create: `agent/context_pack/builder.py`
- Test: `tests/test_context_pack_builder.py`

- [ ] Write failing tests for section order, same-key fact conflicts, authority retention, exact-hit budget survival, partial preservation, failed zero-item packs, and trim traces.
- [ ] Run `python -m pytest tests/test_context_pack_builder.py -q`; expect missing builder.
- [ ] Reject section/item resource mismatches, missing source identity, and empty hashes. Dedupe only identical `(resource_name, item_id, content_hash)`.
- [ ] Group `ContextFact` by key. Use `authoritative_wins` only when one distinct authoritative value exists; otherwise mark unresolved and retain all item IDs.
- [ ] Apply provider item/character budgets, then global character budget. Retain exact hits, then authority order, then provider rank. Never trim current node; trace every omission.
- [ ] Set complete when all sections are ready, partial when content survives with non-ready sections, failed when no requested section has items.
- [ ] Run tests; expect all pass.
- [ ] Commit with `git add agent/context_pack/builder.py tests/test_context_pack_builder.py && git commit -m "feat: assemble bounded context packs"`.

### Task 10: Expose Phase 1 and verify end to end

**Files:**
- Create: `agent/context_pack/__init__.py`
- Modify: `agent/context_pack/manager.py`
- Modify: `agent/context_pack/providers/__init__.py`
- Create: `tests/test_context_pack_integration.py`
- Create: `agent/context_pack/README.md`
- Modify: `README.md`

- [ ] Write failing integration tests: customer name returns complete recipe and only existing visible fields; unrequested OOTB/tree are untouched; missing OOTB yields partial skill results; identical snapshots are deterministic without LLM.
- [ ] Run `python -m pytest tests/test_context_pack_integration.py -q`; expect missing public factory.
- [ ] Add factory and exports:

```python
def create_context_pack_manager(*, embedding_client=None, profiles=None):
    search = LocalResourceSearchTool(embedding_client=embedding_client)
    registry = SourceRegistry([
        CurrentTreeProvider(search),
        DevSkillProvider(search),
        OotbEdslProvider(search),
    ])
    return ContextPackManager(registry, ContextPackBuilder(), profiles=profiles)
```

- [ ] Do not register a fake NamingSQL provider. Requesting it returns `RESOURCE_NOT_REGISTERED` until the migration phase.
- [ ] Document request, ProjectContext, resources, statuses, fallback, authority, customer-name example, and NamingSQL boundary; link from root README.
- [ ] Run focused suites:

```powershell
python -m pytest tests/test_context_pack_models.py tests/test_context_pack_registry_manager.py tests/test_context_pack_search.py tests/test_context_pack_markdown_skill.py tests/test_context_pack_edsl_index.py tests/test_context_pack_current_tree.py tests/test_context_pack_ootb.py tests/test_context_pack_builder.py tests/test_context_pack_integration.py -q
python -m pytest tests/test_context_retrieval.py tests/test_context_resolvers.py tests/test_resource_search_tool.py skills/tree_reference_resolver/tests -q
```

Expected: all listed tests pass.

- [ ] Run final verification:

```powershell
rg -n "CodexPack|CodexPackManager|T[B]D|T[O]DO" README.md agent/context_pack docs/superpowers/specs/2026-07-10-context-pack-manager-design.md
git diff --check
git status --short
python -m pytest -q
```

Expected: no stale names/placeholders, no whitespace errors, only intended files changed, and all tests pass except explicit skips.

- [ ] Commit with `git add agent/context_pack README.md tests/test_context_pack_integration.py && git commit -m "feat: expose phase one context pack manager"`.
- [ ] Handoff exact public imports, factory signature, section metadata contract, error codes, and verification commands. Phase 2 consumes these contracts rather than redefining them.
