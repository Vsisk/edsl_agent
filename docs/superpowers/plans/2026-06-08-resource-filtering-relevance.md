---
change: improve-resource-filtering-dynamic-context-priority
design-doc: docs/superpowers/specs/2026-06-08-resource-filtering-relevance-design.md
base-ref: c3b26f234ab8ac83a124ce140f11686b7c24305b
---

# Resource Filtering Relevance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement query-sensitive resource filtering so `billStatement.fromDate` and similar explicit context mentions survive candidate recall and reach the planner.

**Architecture:** Keep OpenSpec as canonical requirements. Extend `ResourceRoute` with a bounded count hint, translate that hint into explicit filter limits in `ValueLogicGenerator`, improve additive token aliases and context-specific scoring in the environment layer, and make keyword-search merge preserve specific fallback context selections for broad parent-area matches.

**Tech Stack:** Python 3, dataclasses, Pydantic models, `unittest`, local OpenSpec artifacts, existing LLM prompt rendering through `prompt.json`.

---

## File Structure

- Modify `agent/planner/difficulty_router.py`: add `resource_count_hint` constants, parse compatible LLM count fields, preserve existing route behavior.
- Modify `prompt.json`: update `difficulty_router` prompt output contract to include `resource_count_hint`.
- Modify `agent/value_logic_generator.py`: convert route count hints into explicit `top_global_context`, `top_local_context`, `top_bo`, and `top_function` limits.
- Modify `agent/resource_manager/loader/tag_utils.py`: add additive normalized aliases so camel-case, lowercase, underscore, and mixed natural-language adjacency can match.
- Modify `agent/environment/environment.py`: add context-specific scoring, bounded `billStatement` priority, context keyword specificity, and broad-match merge behavior.
- Modify `tests/test_difficulty_router.py`: cover route count parsing, aliases, clamping, and legacy responses.
- Modify `tests/test_value_logic_generator.py`: cover dynamic limit threading and disabled resource groups.
- Modify `tests/test_environment.py`: cover `billStatement.fromDate` recall, broad keyword merge, exact keyword determinism, and non-bill exact-match priority.
- Modify `tests/test_resource_search_tool.py` or existing environment tests: cover normalization behavior through public filtering behavior.
- Modify `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`: mark related tasks complete after each implementation task.

## Task 1: Difficulty Router Count Hint

**Files:**
- Modify: `agent/planner/difficulty_router.py`
- Modify: `prompt.json`
- Modify: `tests/test_difficulty_router.py`
- Modify: `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`

- [ ] **Step 1: Add failing router tests**

Add these tests to `tests/test_difficulty_router.py`:

```python
    def test_parses_resource_count_hint_from_llm_response(self):
        client = FakeClient('{"decision":"bo_only","resource_count_hint":8,"reason":"needs resources"}')

        result = LLMDifficultyRouter(client=client).route_resources(
            node_info=_node_info(),
            user_query="use naming sql with billStatement fromDate",
        )

        self.assertEqual(result, ResourceRoute(use_bo=True, use_function=False, resource_count_hint=8))

    def test_parses_compatible_resource_count_aliases(self):
        client = FakeClient('{"required_resources":["context","function"],"estimated_resource_count":"9"}')

        result = LLMDifficultyRouter(client=client).route_resources(
            node_info=_node_info(),
            user_query="call two functions with context",
        )

        self.assertEqual(result, ResourceRoute(use_bo=False, use_function=True, resource_count_hint=9))

    def test_invalid_resource_count_hint_uses_default(self):
        client = FakeClient('{"decision":"context_only","resource_count_hint":"many"}')

        result = LLMDifficultyRouter(client=client).route_resources(
            node_info=_node_info(),
            user_query="direct context assignment",
        )

        self.assertEqual(result, ResourceRoute(use_bo=False, use_function=False))

    def test_resource_count_hint_is_clamped(self):
        client = FakeClient('{"decision":"full","resource_count_hint":999}')

        result = LLMDifficultyRouter(client=client).route_resources(
            node_info=_node_info(),
            user_query="many explicit resources",
        )

        self.assertEqual(result.resource_count_hint, 20)
```

- [ ] **Step 2: Run router tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_difficulty_router
```

Expected: FAIL because `ResourceRoute` does not yet accept `resource_count_hint`.

- [ ] **Step 3: Implement `ResourceRoute.resource_count_hint`**

In `agent/planner/difficulty_router.py`, add constants after imports:

```python
DEFAULT_RESOURCE_COUNT_HINT = 5
MIN_RESOURCE_COUNT_HINT = 1
MAX_RESOURCE_COUNT_HINT = 20
RESOURCE_COUNT_KEYS = (
    "resource_count_hint",
    "resource_count",
    "estimated_resource_count",
    "mentioned_resource_count",
)
```

Change `ResourceRoute` to:

```python
@dataclass(frozen=True, slots=True)
class ResourceRoute:
    use_bo: bool = True
    use_function: bool = True
    resource_count_hint: int = DEFAULT_RESOURCE_COUNT_HINT
```

Add helper functions before `_route_from_response()`:

```python
def _resource_count_hint_from_response(response: dict[str, Any]) -> int:
    for key in RESOURCE_COUNT_KEYS:
        if key in response:
            return _normalize_resource_count_hint(response.get(key))
    return DEFAULT_RESOURCE_COUNT_HINT


def _normalize_resource_count_hint(value: Any) -> int:
    if isinstance(value, bool):
        return DEFAULT_RESOURCE_COUNT_HINT
    try:
        count = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RESOURCE_COUNT_HINT
    if count < MIN_RESOURCE_COUNT_HINT:
        return DEFAULT_RESOURCE_COUNT_HINT
    return min(count, MAX_RESOURCE_COUNT_HINT)
```

At the start of `_route_from_response()`, compute:

```python
    resource_count_hint = _resource_count_hint_from_response(response)
```

Pass `resource_count_hint=resource_count_hint` into every `ResourceRoute(...)` returned by `_route_from_response()`. Leave `ResourceRoute()` unchanged for conservative full-route fallback, because it now carries the default hint.

- [ ] **Step 4: Update prompt output contract**

In `prompt.json`, update the `difficulty_router` prompt to require a `resource_count_hint` integer in the returned JSON. Preserve existing decision semantics and add rules:

```text
4. Return resource_count_hint as an integer equal to the number of explicit resources mentioned in user_requirement plus a small buffer.
5. Count explicit BO names, naming SQL names, function names, full context paths, or context area plus field mentions.
6. Do not count vague words such as query, mask, customer, amount, or context by themselves.
```

Update the example output shape to include:

```json
{
  "decision": "bo_only",
  "required_resources": ["context", "bo"],
  "resource_count_hint": 7,
  "reason": "..."
}
```

- [ ] **Step 5: Run router tests and mark tasks**

Run:

```powershell
python -m unittest tests.test_difficulty_router
```

Expected: PASS.

In `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`, mark these items done:

```markdown
- [x] 1.1 Add difficulty router tests for parsing a valid resource count hint and falling back when the hint is missing or invalid.
- [x] 2.1 Extend `ResourceRoute` with a bounded `resource_count_hint` field and preserve current defaults for existing call sites.
- [x] 2.2 Update `_route_from_response()` to parse compatible resource count keys, clamp invalid values, and keep BO/function route parsing backward-compatible.
- [x] 2.3 Update the `difficulty_router` prompt in `prompt.json` to require a resource count value equal to explicit query resource mentions plus buffer.
- [x] 2.4 Document or encode default, minimum, and maximum resource count hint constants near the router parsing logic.
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add agent/planner/difficulty_router.py prompt.json tests/test_difficulty_router.py openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md
git commit -m "feat: route resource count hints for filtering"
```

Expected: commit succeeds.

## Task 2: Dynamic Filter Limits

**Files:**
- Modify: `agent/value_logic_generator.py`
- Modify: `tests/test_value_logic_generator.py`
- Modify: `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`

- [ ] **Step 1: Add failing dynamic-limit tests**

In `tests/test_value_logic_generator.py`, change `FakeResourceRoute` to accept the new hint:

```python
class FakeResourceRoute:
    def __init__(self, *, use_bo: bool, use_function: bool, resource_count_hint: int = 5):
        self.use_bo = use_bo
        self.use_function = use_function
        self.resource_count_hint = resource_count_hint
```

Add this test:

```python
    def test_resource_count_hint_expands_filter_limits(self):
        planner = FakePlanner()
        resource_filter = FakeResourceFilter(
            {
                "bo": [{"resource_id": "bo.0000"}],
                "function": [{"resource_id": "func.0001"}],
                "local_context": [{"resource_id": "local.0002"}],
                "global_context": [{"resource_id": "ctx.0001"}],
            }
        )
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=resource_filter,
            llm_difficulty_router=FakeDifficultyRouter(
                FakeResourceRoute(use_bo=True, use_function=True, resource_count_hint=9)
            ),
            llm_planner=planner,
        )

        generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1]",
                node={
                    "node_id": "node-1",
                    "tree_node_type": "simple_leaf",
                    "xml_name_property": {"xml_name": "SUB_INFO"},
                    "annotation": "user information node",
                },
                query="use several resources",
                edsl_tree=sample_edsl_tree_payload(),
            )
        )

        self.assertEqual(resource_filter.calls[0]["limits"]["global_context"], 9)
        self.assertEqual(resource_filter.calls[0]["limits"]["local_context"], 9)
        self.assertEqual(resource_filter.calls[0]["limits"]["bo"], 9)
        self.assertEqual(resource_filter.calls[0]["limits"]["function"], 9)
```

Add this test:

```python
    def test_resource_count_hint_keeps_disabled_groups_zero(self):
        planner = FakePlanner()
        resource_filter = FakeResourceFilter(
            {
                "bo": [{"resource_id": "bo.0000"}],
                "function": [{"resource_id": "func.0001"}],
                "local_context": [{"resource_id": "local.0002"}],
                "global_context": [{"resource_id": "ctx.0001"}],
            }
        )
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=resource_filter,
            llm_difficulty_router=FakeDifficultyRouter(
                FakeResourceRoute(use_bo=False, use_function=False, resource_count_hint=12)
            ),
            llm_planner=planner,
        )

        generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1]",
                node={
                    "node_id": "node-1",
                    "tree_node_type": "simple_leaf",
                    "xml_name_property": {"xml_name": "SUB_INFO"},
                    "annotation": "user information node",
                },
                query="context only but many mentions",
                edsl_tree=sample_edsl_tree_payload(),
            )
        )

        self.assertEqual(resource_filter.calls[0]["limits"]["global_context"], 12)
        self.assertEqual(resource_filter.calls[0]["limits"]["local_context"], 12)
        self.assertEqual(resource_filter.calls[0]["limits"]["bo"], 0)
        self.assertEqual(resource_filter.calls[0]["limits"]["function"], 0)
```

- [ ] **Step 2: Run value logic tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_value_logic_generator
```

Expected: FAIL because context limits remain default 5 and BO/function limits are hard-coded to 5.

- [ ] **Step 3: Implement dynamic limit helper**

In `agent/value_logic_generator.py`, add constants near imports:

```python
DEFAULT_CONTEXT_LIMIT = 5
DEFAULT_RESOURCE_LIMIT = 5
MAX_DYNAMIC_CONTEXT_LIMIT = 12
MAX_DYNAMIC_RESOURCE_LIMIT = 10
```

Add helper near `_qualify_function_resource_calls()` or as a method on `ValueLogicGenerator`:

```python
def _clamp_limit(value: Any, *, default: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    if normalized < default:
        return default
    return min(normalized, maximum)


def _resource_limits_from_route(route: ResourceRoute) -> dict[str, int]:
    context_limit = _clamp_limit(
        getattr(route, "resource_count_hint", DEFAULT_CONTEXT_LIMIT),
        default=DEFAULT_CONTEXT_LIMIT,
        maximum=MAX_DYNAMIC_CONTEXT_LIMIT,
    )
    resource_limit = _clamp_limit(
        getattr(route, "resource_count_hint", DEFAULT_RESOURCE_LIMIT),
        default=DEFAULT_RESOURCE_LIMIT,
        maximum=MAX_DYNAMIC_RESOURCE_LIMIT,
    )
    return {
        "top_global_context": context_limit,
        "top_local_context": context_limit,
        "top_bo": resource_limit if route.use_bo else 0,
        "top_function": resource_limit if route.use_function else 0,
    }
```

In `_generate_expression_by_plan()`, replace the `build_filtered_environment()` call with:

```python
        resource_limits = _resource_limits_from_route(route)
        filtered_env = build_filtered_environment(
            node_info=node_info,
            user_query=request.query,
            registry=ctx.resources.loaded,
            llm_resource_filter=self.llm_resource_filter,
            **resource_limits,
        )
```

- [ ] **Step 4: Run value logic tests and mark tasks**

Run:

```powershell
python -m unittest tests.test_value_logic_generator
```

Expected: PASS.

In `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`, mark:

```markdown
- [x] 1.2 Add value logic generator tests that verify route resource count hints change filtering limits while disabled BO/function groups remain zero.
- [x] 3.1 Add a small helper in `ValueLogicGenerator` to convert `resource_count_hint` into `top_global_context`, `top_local_context`, `top_bo`, and `top_function` values.
- [x] 3.2 Thread dynamic context limits into `build_filtered_environment()` instead of relying on fixed default context limits.
- [x] 3.3 Keep disabled BO/function groups at zero regardless of the resource count hint.
- [x] 3.4 Bound all dynamic limits to avoid unbounded prompt growth.
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add agent/value_logic_generator.py tests/test_value_logic_generator.py openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md
git commit -m "feat: size resource filters from route hints"
```

Expected: commit succeeds.

## Task 3: Token Aliases And Context Recall

**Files:**
- Modify: `agent/resource_manager/loader/tag_utils.py`
- Modify: `agent/environment/environment.py`
- Modify: `tests/test_environment.py`
- Modify: `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`

- [ ] **Step 1: Add failing recall tests**

In `tests/test_environment.py`, add helper payload:

```python
def bill_statement_context_payload():
    return {
        "context": {
            "global_context": {
                "property_name": "$ctx$",
                "sub_properties": [
                    {
                        "property_name": "billStatement",
                        "property_type": "system",
                        "return_type": {
                            "data_type": "bo",
                            "data_type_name": "BB_BILL_STATEMENT",
                            "is_list": False,
                        },
                        "children": [
                            {
                                "property_name": "TO_DATE",
                                "annotation": "to date",
                                "return_type": {"data_type": "basic", "data_type_name": "STRING", "is_list": False},
                            },
                            {
                                "property_name": "START_DATE",
                                "annotation": "start date",
                                "return_type": {"data_type": "basic", "data_type_name": "STRING", "is_list": False},
                            },
                            {
                                "property_name": "END_DATE",
                                "annotation": "end date",
                                "return_type": {"data_type": "basic", "data_type_name": "STRING", "is_list": False},
                            },
                            {
                                "property_name": "FROM_DATE",
                                "annotation": "from date",
                                "return_type": {"data_type": "basic", "data_type_name": "STRING", "is_list": False},
                            },
                        ],
                    },
                    {
                        "property_name": "order",
                        "property_type": "system",
                        "return_type": {
                            "data_type": "bo",
                            "data_type_name": "ORDER",
                            "is_list": False,
                        },
                        "children": [
                            {
                                "property_name": "ORDER_ID",
                                "annotation": "order id",
                                "return_type": {"data_type": "basic", "data_type_name": "STRING", "is_list": False},
                            }
                        ],
                    },
                ],
            }
        },
        "bo": {},
        "function": {},
    }
```

Add loader helper:

```python
class StaticResourceLoader(ResourceLoader):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload

    def get_resource_data(self, site_id, project_id):
        return self.payload
```

Add this test:

```python
    def test_recalls_bill_statement_from_date_without_full_context_path(self):
        loaded = StaticResourceLoader(bill_statement_context_payload()).load_resource(
            "site1",
            "project1",
            sample_edsl_tree_payload(),
        )
        node_info = NodeDef(node_id="node-1", node_path="$.mapping_content.children[1]", node_name="SUB_INFO")

        environment = build_filtered_environment(
            node_info,
            "use billStatement fromDate as namingSql query condition",
            loaded,
            top_global_context=1,
            top_local_context=0,
            top_bo=0,
            top_function=0,
            llm_resource_filter=FailingResourceFilter(),
        )

        self.assertEqual(
            [context.context_name for context in environment.selected_global_contexts],
            ["$ctx$.billStatement.FROM_DATE"],
        )
```

Add this test:

```python
    def test_recalls_mixed_natural_language_resource_name_tokens(self):
        loaded = StaticResourceLoader(bill_statement_context_payload()).load_resource(
            "site1",
            "project1",
            sample_edsl_tree_payload(),
        )
        node_info = NodeDef(node_id="node-1", node_path="$.mapping_content.children[1]", node_name="SUB_INFO")

        environment = build_filtered_environment(
            node_info,
            "使用billStatement里的fromDate作为namingSql查询条件",
            loaded,
            top_global_context=1,
            top_local_context=0,
            top_bo=0,
            top_function=0,
            llm_resource_filter=FailingResourceFilter(),
        )

        self.assertEqual(
            [context.context_name for context in environment.selected_global_contexts],
            ["$ctx$.billStatement.FROM_DATE"],
        )
```

Add this test:

```python
    def test_non_bill_statement_exact_match_can_outrank_bill_statement_priority(self):
        loaded = StaticResourceLoader(bill_statement_context_payload()).load_resource(
            "site1",
            "project1",
            sample_edsl_tree_payload(),
        )
        node_info = NodeDef(node_id="node-1", node_path="$.mapping_content.children[1]", node_name="SUB_INFO")

        environment = build_filtered_environment(
            node_info,
            "use order ORDER_ID",
            loaded,
            top_global_context=1,
            top_local_context=0,
            top_bo=0,
            top_function=0,
            llm_resource_filter=FailingResourceFilter(),
        )

        self.assertEqual(
            [context.context_name for context in environment.selected_global_contexts],
            ["$ctx$.order.ORDER_ID"],
        )
```

- [ ] **Step 2: Run environment tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_environment
```

Expected: at least the `FROM_DATE` recall tests fail.

- [ ] **Step 3: Add additive token aliases**

In `agent/resource_manager/loader/tag_utils.py`, add:

```python
ALPHANUM_PATTERN = re.compile(r"[0-9A-Za-z]+")
NON_ALPHANUM_PATTERN = re.compile(r"[^0-9A-Za-z]+")
```

Add helper:

```python
def _compact_ascii_token(value: str) -> str:
    return "".join(ALPHANUM_PATTERN.findall(value)).lower()


def _append_aliases(tokens: List[str], segment: str, filter_stop_words: bool) -> None:
    compact = _compact_ascii_token(segment)
    if len(compact) < 3:
        return
    if filter_stop_words and compact in STOP_WORDS:
        return
    _append_unique(tokens, compact)
```

In `_extract_tokens()`, after `tokens.extend(TOKEN_PATTERN.findall(segment))`, call:

```python
        _append_aliases(tokens, segment, filter_stop_words)
```

Keep existing stop-word filtering at the end.

- [ ] **Step 4: Add context-specific scoring**

In `agent/environment/environment.py`:

Extend `_ScoredResource`:

```python
    priority_score: float
```

Add constants:

```python
CONTEXT_FIELD_EXACT_BONUS = 2.0
CONTEXT_PARENT_FIELD_PAIR_BONUS = 1.0
BILL_STATEMENT_PRIORITY_SCORE = 1.0
BILL_STATEMENT_TOKENS = {"billstatement", "bill", "statement", "bbbillstatement"}
```

Change `_select_top_resources()` to accept `group`:

```python
def _select_top_resources(resources: list, weighted_tokens: dict[str, float], top_n: int, group: str) -> list:
```

Pass group from all four call sites.

Change `_score_resource()` signature:

```python
def _score_resource(resource: object, weighted_tokens: dict[str, float], index: int, group: str) -> _ScoredResource:
```

After generic token scoring, add:

```python
    if group in {"global_context", "local_context"}:
        score += _context_specificity_bonus(resource, weighted_tokens)
    priority_score = _context_priority_score(resource, weighted_tokens, group)
```

Sort with:

```python
            -scored.priority_score,
```

before `scored.index`.

Add helpers:

```python
def _context_specificity_bonus(resource: object, weighted_tokens: dict[str, float]) -> float:
    context_name = str(getattr(resource, "context_name", "") or "")
    parts = [_normalize_resource_alias(part) for part in context_name.split(".") if part]
    query_tokens = set(weighted_tokens)
    has_field = bool(parts and parts[-1] in query_tokens)
    has_parent = any(part in query_tokens for part in parts[:-1])
    bonus = 0.0
    if has_field:
        bonus += CONTEXT_FIELD_EXACT_BONUS
    if has_field and has_parent:
        bonus += CONTEXT_PARENT_FIELD_PAIR_BONUS
    return bonus


def _context_priority_score(resource: object, weighted_tokens: dict[str, float], group: str) -> float:
    if group != "global_context":
        return 0.0
    context_name = str(getattr(resource, "context_name", "") or "").lower()
    if not context_name.startswith("$ctx$.billstatement."):
        return 0.0
    if not (set(weighted_tokens) & BILL_STATEMENT_TOKENS):
        return 0.0
    return BILL_STATEMENT_PRIORITY_SCORE


def _normalize_resource_alias(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())
```

Return `_ScoredResource(..., priority_score=priority_score, ...)`.

- [ ] **Step 5: Run environment tests and mark tasks**

Run:

```powershell
python -m unittest tests.test_environment
```

Expected: PASS.

In OpenSpec `tasks.md`, mark:

```markdown
- [x] 1.3 Add environment filtering tests for a `billStatement.fromDate` context used as a naming SQL parameter without a full `$ctx$` path.
- [x] 1.4 Add environment filtering tests for mixed natural-language/resource-name tokenization around `billStatement` and `fromDate`.
- [x] 4.1 Improve token normalization so camel-case, all-lowercase, and underscore forms like `fromDate`, `fromdate`, and `FROM_DATE` can match each other.
- [x] 4.2 Preserve mixed natural-language/resource-name tokens without breaking existing stop-word filtering behavior.
- [x] 4.3 Add context scoring support for recognizing parent-area plus child-field mentions such as `billStatement` plus `fromDate`.
- [x] 4.4 Add a deterministic `billStatement` global context priority boost or tie-breaker that only applies when bill statement context is relevant.
- [x] 4.5 Ensure a stronger exact match outside `billStatement` can still outrank the `billStatement` priority boost.
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add agent/resource_manager/loader/tag_utils.py agent/environment/environment.py tests/test_environment.py openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md
git commit -m "feat: improve context recall scoring"
```

Expected: commit succeeds.

## Task 4: Keyword Search Merge Specificity

**Files:**
- Modify: `agent/environment/environment.py`
- Modify: `tests/test_environment.py`
- Modify: `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`

- [ ] **Step 1: Add failing merge tests**

In `tests/test_environment.py`, add:

```python
    def test_broad_context_keyword_search_preserves_specific_fallback_selection(self):
        loaded = StaticResourceLoader(bill_statement_context_payload()).load_resource(
            "site1",
            "project1",
            sample_edsl_tree_payload(),
        )
        node_info = NodeDef(node_id="node-1", node_path="$.mapping_content.children[1]", node_name="SUB_INFO")
        llm_filter = FakeResourceFilter(
            {
                "global_context": [{"resource_id": "ctx.0003", "reason": "specific fallback"}],
                "local_context": [],
                "bo": [],
                "function": [],
            },
            search_commands={
                "commands": [
                    {
                        "tool": "resource_keyword_search",
                        "group": "global_context",
                        "keyword": "billStatement",
                    }
                ]
            },
        )

        environment = build_filtered_environment(
            node_info,
            "use billStatement fromDate as namingSql query condition",
            loaded,
            top_global_context=1,
            top_local_context=0,
            top_bo=0,
            top_function=0,
            llm_resource_filter=llm_filter,
        )

        self.assertEqual(
            [context.context_name for context in environment.selected_global_contexts],
            ["$ctx$.billStatement.FROM_DATE"],
        )
```

Add:

```python
    def test_exact_context_keyword_search_remains_deterministic(self):
        loaded = StaticResourceLoader(bill_statement_context_payload()).load_resource(
            "site1",
            "project1",
            sample_edsl_tree_payload(),
        )
        node_info = NodeDef(node_id="node-1", node_path="$.mapping_content.children[1]", node_name="SUB_INFO")
        llm_filter = FakeResourceFilter(
            {
                "global_context": [{"resource_id": "ctx.0000", "reason": "fallback should lose to exact path"}],
                "local_context": [],
                "bo": [],
                "function": [],
            },
            search_commands={
                "commands": [
                    {
                        "tool": "resource_keyword_search",
                        "group": "global_context",
                        "keyword": "$ctx$.billStatement.FROM_DATE",
                    }
                ]
            },
        )

        environment = build_filtered_environment(
            node_info,
            "use $ctx$.billStatement.FROM_DATE",
            loaded,
            top_global_context=1,
            top_local_context=0,
            top_bo=0,
            top_function=0,
            llm_resource_filter=llm_filter,
        )

        self.assertEqual(
            [context.context_name for context in environment.selected_global_contexts],
            ["$ctx$.billStatement.FROM_DATE"],
        )
```

- [ ] **Step 2: Run environment tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_environment
```

Expected: broad keyword merge test fails because tool-search overrides fallback.

- [ ] **Step 3: Track broad-match groups**

In `agent/environment/environment.py`, extend `_ToolSearchResult`:

```python
    broad_match_groups: set[str]
```

Initialize:

```python
    broad_match_groups: set[str] = set()
```

Inside command execution, before iterating search results:

```python
        is_broad_context_match = _is_broad_context_keyword(group, keyword, search_space[group])
```

When a command found any result and `is_broad_context_match` is true, add:

```python
            broad_match_groups.add(group)
```

Return:

```python
    return _ToolSearchResult(
        selected_by_group=selected_by_group,
        matched_groups=matched_groups,
        broad_match_groups=broad_match_groups,
    )
```

Add helper:

```python
def _is_broad_context_keyword(group: str, keyword: str, items: list[str]) -> bool:
    if group not in {"global_context", "local_context"}:
        return False
    normalized = keyword.strip().lower()
    if normalized.startswith(("$ctx$.", "$local$.", "$iter$.")):
        return False
    matches = ResourceKeywordSearchTool().search(items, keyword)
    return len(matches) > 1
```

- [ ] **Step 4: Merge broad context results fallback-first**

Replace `_merge_tool_search_and_fallback()` body with:

```python
    if tool_search_result is None:
        return fallback_selected_by_group

    merged: dict[str, list] = {}
    for group, fallback_resources in fallback_selected_by_group.items():
        if group not in tool_search_result.matched_groups:
            merged[group] = fallback_resources
            continue
        if group in tool_search_result.broad_match_groups:
            limit = len(fallback_resources) or len(tool_search_result.selected_by_group[group])
            merged[group] = _merge_resource_lists(
                fallback_resources,
                tool_search_result.selected_by_group[group],
                limit=limit,
            )
            continue
        merged[group] = tool_search_result.selected_by_group[group]
    return merged
```

Add:

```python
def _merge_resource_lists(primary: list, secondary: list, *, limit: int) -> list:
    selected: list = []
    selected_ids: set[str] = set()
    for resource in [*primary, *secondary]:
        resource_id = getattr(resource, "resource_id", "")
        if resource_id in selected_ids:
            continue
        selected.append(resource)
        selected_ids.add(resource_id)
        if len(selected) >= limit:
            break
    return selected
```

- [ ] **Step 5: Run environment tests and mark tasks**

Run:

```powershell
python -m unittest tests.test_environment
```

Expected: PASS.

Mark in OpenSpec `tasks.md`:

```markdown
- [x] 1.5 Add keyword search merge tests showing broad `billStatement` matches preserve a more specific fallback-selected field, while exact full-path matches remain deterministic.
- [x] 5.1 Distinguish exact full-path context keyword matches from broad parent-area context keyword matches.
- [x] 5.2 Merge broad context keyword-search results with fallback selections instead of replacing the whole group.
- [x] 5.3 Preserve current deterministic override behavior for exact BO names, naming SQL names, function names, and full context paths.
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add agent/environment/environment.py tests/test_environment.py openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md
git commit -m "feat: preserve specific context matches"
```

Expected: commit succeeds.

## Task 5: End-To-End Verification And Cleanup

**Files:**
- Modify: `openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md`
- No code file changes unless verification reveals a defect in the preceding tasks.

- [ ] **Step 1: Run focused test suites**

Run:

```powershell
python -m unittest tests.test_difficulty_router tests.test_environment tests.test_value_logic_generator
```

Expected: PASS.

- [ ] **Step 2: Run related regression suites**

Run:

```powershell
python -m unittest tests.test_planner_prompt tests.test_resource_loader tests.test_llm_planner tests.test_resource_search_tool
```

Expected: PASS.

- [ ] **Step 3: Run manual smoke check**

Run this inline script:

```powershell
@'
from tests.test_environment import (
    StaticResourceLoader,
    bill_statement_context_payload,
    sample_edsl_tree_payload,
    FailingResourceFilter,
)
from agent.environment.environment import build_filtered_environment
from agent.models import NodeDef

loaded = StaticResourceLoader(bill_statement_context_payload()).load_resource(
    "site1",
    "project1",
    sample_edsl_tree_payload(),
)
env = build_filtered_environment(
    NodeDef(node_id="node-1", node_path="$.mapping_content.children[1]", node_name="SUB_INFO"),
    "use billStatement fromDate as namingSql query condition",
    loaded,
    top_global_context=1,
    top_local_context=0,
    top_bo=0,
    top_function=0,
    llm_resource_filter=FailingResourceFilter(),
)
print([ctx.context_name for ctx in env.selected_global_contexts])
'@ | python -
```

Expected output:

```text
['$ctx$.billStatement.FROM_DATE']
```

- [ ] **Step 4: Check OpenSpec status**

Run:

```powershell
openspec status --change "improve-resource-filtering-dynamic-context-priority"
```

Expected: `All artifacts complete!`

- [ ] **Step 5: Mark verification tasks**

In OpenSpec `tasks.md`, mark:

```markdown
- [x] 6.1 Run `python -m unittest tests.test_difficulty_router tests.test_environment tests.test_value_logic_generator`.
- [x] 6.2 Run related planner/resource loader tests if prompt or tag changes affect snapshots: `python -m unittest tests.test_planner_prompt tests.test_resource_loader tests.test_llm_planner`.
- [x] 6.3 Manually inspect the generated filtered environment for the `billStatement.fromDate` naming SQL bad case and confirm the expected context is present.
- [x] 6.4 Run `openspec status --change "improve-resource-filtering-dynamic-context-priority"` and confirm the change is apply-ready.
```

- [ ] **Step 6: Inspect final diff**

Run:

```powershell
git status --short
git diff --stat HEAD
```

Expected: only intentional files remain modified or untracked.

- [ ] **Step 7: Commit verification**

Run:

```powershell
git add openspec/changes/improve-resource-filtering-dynamic-context-priority/tasks.md
git commit -m "test: verify resource filtering relevance"
```

Expected: commit succeeds if `tasks.md` changed. If no files changed, skip this commit and record that verification passed without additional changes.
