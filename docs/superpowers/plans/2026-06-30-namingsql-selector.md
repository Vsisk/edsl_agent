# NamingSQL Selector MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone NamingSQL selection route that profiles loaded SQL definitions, selects exactly one BO, validates parameter bindings, controls full-table fallback, and constrains expression planning to the approved SQL.

**Architecture:** Add a focused `agent/naming_sql_selector` package containing contracts, profile construction, request-spec generation, BO resolution, binding, ranking, and orchestration. Extend resource loading only enough to preserve raw SQL metadata and cache profiles by site. Integrate through a thin branch in `ValueLogicGenerator`; the planner sees one selected NamingSQL and a fixed binding plan, then a local validator enforces that contract.

**Tech Stack:** Python 3.11+, Pydantic v2, dataclasses, standard-library regex/token matching, `unittest`, existing planner/AST pipeline.

---

## File Map

- Create `agent/naming_sql_selector/models.py`: public request/result contracts and internal profile/spec/binding models.
- Create `agent/naming_sql_selector/profile_builder.py`: conservative SQL parsing and profile construction.
- Create `agent/naming_sql_selector/knowledge.py`: bounded site-knowledge retriever interface and no-op implementation.
- Create `agent/naming_sql_selector/spec_generator.py`: deterministic MVP `DataAccessSpec` generation.
- Create `agent/naming_sql_selector/selector.py`: BO recall/review, binding, ranking, fallback policy, and standalone facade.
- Create `agent/naming_sql_selector/plan_validator.py`: verify planner fetch nodes against the selected SQL and binding plan.
- Create `agent/naming_sql_selector/__init__.py`: stable public exports.
- Modify `agent/resource_manager/loader/registry_models.py`: preserve `label_name` and `sql_command`.
- Modify `agent/resource_manager/loader/resource_loader.py`: cache and expose profiles by `site_id`.
- Modify `agent/models.py`: accept the structured route signal.
- Modify `agent/environment/environment.py`: carry the optional selector result in the filtered environment.
- Modify `agent/value_logic_generator.py`: invoke selector on the NamingSQL route and narrow planner resources.
- Modify `agent/planner/llm_planner.py`: summarize one selected SQL and its fixed bindings.
- Modify `prompt.json`: explicitly forbid NamingSQL reselection and binding changes.
- Create `tests/test_naming_sql_profile_builder.py`: profile parsing and loader-cache behavior.
- Create `tests/test_naming_sql_selector.py`: spec, BO, binding, scoring, reviewer, and fallback behavior.
- Create `tests/test_naming_sql_plan_validator.py`: planner contract enforcement.
- Modify `tests/test_resource_loader.py`: raw SQL metadata preservation.
- Modify `tests/test_value_logic_generator.py`: expression-route integration.
- Modify `tests/test_llm_planner.py` and `tests/test_planner_prompt.py`: selected-SQL summary and prompt contract.

### Task 1: Preserve Raw NamingSQL Metadata

**Files:**
- Modify: `agent/resource_manager/loader/registry_models.py`
- Modify: `tests/test_resource_loader.py`

- [ ] **Step 1: Write the failing loader test**

Add `label_name` and `sql_command` to the NamingSQL fixture in `sample_bo_payload()`, then add:

```python
def test_bo_loader_preserves_naming_sql_profile_source_fields():
    registry = load_bo_registry_by_json(sample_bo_payload())

    naming_sql = registry["BB_BAK_TRANS"].naming_sql_list[0]

    assert naming_sql.label_name == "Query AR transaction by end date"
    assert naming_sql.sql_command == (
        "SELECT LOG_ID FROM BB_BAK_TRANS "
        "WHERE END_DATE = :END_DATE"
    )
```

- [ ] **Step 2: Run the test and verify the missing fields fail**

Run:

```powershell
python -m unittest tests.test_resource_loader -v
```

Expected: `AttributeError` for `label_name` or `sql_command`.

- [ ] **Step 3: Extend the registry model without changing loader control flow**

Change `NamingSqlDefTerm` to:

```python
class NamingSqlDefTerm(BaseModel):
    naming_sql_id: str = Field(..., description="Named SQL id")
    sql_name: str = Field(..., description="SQL name")
    label_name: Optional[str] = Field(default=None, description="Display label")
    sql_description: Optional[str] = Field(None, description="SQL description")
    sql_command: Optional[str] = Field(default=None, description="SQL command")
    param_list: List[ParamTerm] = Field(default_factory=list, description="Parameter list")
```

`bo_loader._collect_naming_sql_list()` already constructs this model from the complete dictionary, so no additional loader branch is required.

- [ ] **Step 4: Run loader and registry tests**

Run:

```powershell
python -m unittest tests.test_resource_loader tests.test_registry_models -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the metadata preservation slice**

```powershell
git add agent/resource_manager/loader/registry_models.py tests/test_resource_loader.py
git commit -m "feat: preserve naming sql source metadata"
```

### Task 2: Build and Cache NamingSQL Profiles

**Files:**
- Create: `agent/naming_sql_selector/models.py`
- Create: `agent/naming_sql_selector/profile_builder.py`
- Create: `agent/naming_sql_selector/__init__.py`
- Modify: `agent/resource_manager/loader/resource_loader.py`
- Create: `tests/test_naming_sql_profile_builder.py`

- [ ] **Step 1: Write failing profile-builder tests**

Create `tests/test_naming_sql_profile_builder.py` with fixtures for a scoped SQL, `WHERE 1=1`, and malformed SQL:

```python
import unittest

from agent.naming_sql_selector.profile_builder import NamingSqlProfileBuilder
from agent.resource_manager.loader.registry_models import NamingSqlDefTerm, ParamTerm


def sql_def(command: str | None) -> NamingSqlDefTerm:
    return NamingSqlDefTerm(
        naming_sql_id="sql-1",
        sql_name="queryByAcctAndDate",
        label_name="Query account transactions",
        sql_description="Account transaction lookup",
        sql_command=command,
        param_list=[ParamTerm(param_name="ACCT_ID", data_type_name="long")],
    )


class NamingSqlProfileBuilderTest(unittest.TestCase):
    def test_extracts_effective_filter_fields(self):
        profile = NamingSqlProfileBuilder().build(
            site_id="site-a",
            bo_name="AR_TRANS",
            definition=sql_def(
                "SELECT TRANS_ID FROM AR_TRANS "
                "WHERE 1=1 AND ACCT_ID = :ACCT_ID AND TRANS_DATE >= :START_DATE"
            ),
        )

        self.assertEqual(profile.site_id, "site-a")
        self.assertEqual(profile.filter_fields, ["ACCT_ID", "TRANS_DATE"])
        self.assertFalse(profile.is_full_table)
        self.assertIn("acct", profile.scope_tags)

    def test_where_one_equals_one_is_fallback_only(self):
        profile = NamingSqlProfileBuilder().build(
            site_id="site-a",
            bo_name="AR_TRANS",
            definition=sql_def("SELECT * FROM AR_TRANS WHERE 1=1"),
        )

        self.assertTrue(profile.is_full_table)
        self.assertEqual(profile.filter_fields, [])

    def test_missing_or_unparseable_sql_is_conservative(self):
        profile = NamingSqlProfileBuilder().build(
            site_id="site-a",
            bo_name="AR_TRANS",
            definition=sql_def(None),
        )

        self.assertTrue(profile.is_full_table)
```

- [ ] **Step 2: Run the new tests and verify imports fail**

Run:

```powershell
python -m unittest tests.test_naming_sql_profile_builder -v
```

Expected: import failure for `agent.naming_sql_selector`.

- [ ] **Step 3: Add the profile contracts**

In `agent/naming_sql_selector/models.py`, define strict Pydantic models:

```python
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SelectorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NamingSqlParamProfile(SelectorModel):
    name: str
    data_type: str = ""
    is_list: bool = False


class NamingSqlProfile(SelectorModel):
    site_id: str
    bo_name: str
    naming_sql_id: str
    sql_name: str
    label_name: str = ""
    sql_description: str = ""
    params: list[NamingSqlParamProfile] = Field(default_factory=list)
    filter_fields: list[str] = Field(default_factory=list)
    scope_tags: list[str] = Field(default_factory=list)
    is_full_table: bool = True
    search_text: str = ""
```

- [ ] **Step 4: Implement conservative profile construction**

In `agent/naming_sql_selector/profile_builder.py`, implement normalized tokens and predicate extraction. Only fields directly followed by a comparison operator count as effective filters; `1=1` is ignored:

```python
import re

from agent.naming_sql_selector.models import NamingSqlParamProfile, NamingSqlProfile
from agent.resource_manager.loader.registry_models import NamingSqlDefTerm
from agent.resource_manager.loader.tag_utils import tokenize_text

_PREDICATE_RE = re.compile(
    r"(?i)(?:\b[A-Z_][A-Z0-9_]*\.)?([A-Z_][A-Z0-9_]*)\s*"
    r"(?:=|<>|!=|<=|>=|<|>|\bLIKE\b|\bIN\b|\bBETWEEN\b|\bIS\b)"
)


class NamingSqlProfileBuilder:
    def build(self, *, site_id: str, bo_name: str, definition: NamingSqlDefTerm) -> NamingSqlProfile:
        command = str(definition.sql_command or "")
        fields = []
        for match in _PREDICATE_RE.finditer(command):
            field = match.group(1).upper()
            if field != "1" and field not in fields:
                fields.append(field)
        source_text = " ".join(
            part for part in (
                definition.sql_name,
                definition.label_name or "",
                definition.sql_description or "",
                " ".join(fields),
                " ".join(param.param_name for param in definition.param_list),
            ) if part
        )
        tags = tokenize_text(source_text)
        return NamingSqlProfile(
            site_id=site_id,
            bo_name=bo_name,
            naming_sql_id=definition.naming_sql_id,
            sql_name=definition.sql_name,
            label_name=definition.label_name or "",
            sql_description=definition.sql_description or "",
            params=[
                NamingSqlParamProfile(
                    name=param.param_name,
                    data_type=param.data_type_name,
                    is_list=param.is_list,
                )
                for param in definition.param_list
            ],
            filter_fields=fields,
            scope_tags=tags,
            is_full_table=not fields,
            search_text=" ".join(tags),
        )
```

- [ ] **Step 5: Add profile cache coverage before implementation**

Add a test that calls `ResourceLoader.load_resource()` twice for the same `site_id` with different `project_id` values and asserts the returned profile objects come from the same site cache and contain only `site_id` as their scope identity.

- [ ] **Step 6: Extend LoadedResource and ResourceLoader**

Add `naming_sql_profiles: dict[str, list[NamingSqlProfile]] = field(default_factory=dict)` to the end of `LoadedResource`, preserving compatibility with existing constructors. Add `naming_sql_profile_cache: dict[str, dict[str, list[NamingSqlProfile]]]` to `ResourceLoader`. After BO loading, build profiles grouped by BO and cache them under `site_id`:

```python
def _build_naming_sql_profiles(site_id: str, bo_registry: Dict[str, BoRegistry]):
    builder = NamingSqlProfileBuilder()
    return {
        bo_name: [
            builder.build(site_id=site_id, bo_name=bo_name, definition=item)
            for item in bo.naming_sql_list
        ]
        for bo_name, bo in bo_registry.items()
    }
```

Keep source-change detection private to `ResourceLoader`; for the local-file MVP, invalidating the profile cache whenever the corresponding BO cache is rebuilt is sufficient.

- [ ] **Step 7: Export the stable profile API and run tests**

Export `NamingSqlProfile` and `NamingSqlProfileBuilder` from `agent/naming_sql_selector/__init__.py` and run:

```powershell
python -m unittest tests.test_naming_sql_profile_builder tests.test_resource_loader -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit profile construction**

```powershell
git add agent/naming_sql_selector agent/resource_manager/loader/resource_loader.py tests/test_naming_sql_profile_builder.py
git commit -m "feat: build naming sql profiles"
```

### Task 3: Generate the Session-Local DataAccessSpec

**Files:**
- Modify: `agent/naming_sql_selector/models.py`
- Create: `agent/naming_sql_selector/knowledge.py`
- Create: `agent/naming_sql_selector/spec_generator.py`
- Create: `tests/test_naming_sql_selector.py`

- [ ] **Step 1: Write failing specification and knowledge tests**

Create `tests/test_naming_sql_selector.py` with:

```python
import unittest

from agent.naming_sql_selector.knowledge import DevelopmentKnowledge, StaticDevelopmentKnowledgeRetriever
from agent.naming_sql_selector.models import NamingSqlSelectionRequest
from agent.naming_sql_selector.spec_generator import DataAccessSpecGenerator


class DataAccessSpecGeneratorTest(unittest.TestCase):
    def test_combines_structured_signal_context_and_site_knowledge(self):
        retriever = StaticDevelopmentKnowledgeRetriever(
            {
                "site-a": [
                    DevelopmentKnowledge(
                        text="AR transaction uses BO_AR_TRANS and ACCT_ID",
                        bo_names=["BO_AR_TRANS"],
                        semantic_tags=["ar", "transaction", "account"],
                        param_aliases={"ACCT_ID": ["account id"]},
                    )
                ]
            }
        )
        request = NamingSqlSelectionRequest(
            site_id="site-a",
            query="查询账户 AR Trans",
            node={"annotation": "AR transaction fee"},
            parent_node={"annotation": "account detail"},
            structured_spec={"requires_naming_sql": True, "scope_terms": ["account"]},
            available_context=[
                {"name": "account id", "source_ref": "$ctx$.account.ACCT_ID", "data_type": "long"}
            ],
        )

        spec = DataAccessSpecGenerator(retriever=retriever).generate(request)

        self.assertTrue(spec.requires_naming_sql)
        self.assertIn("BO_AR_TRANS", spec.bo_hints)
        self.assertIn("account", spec.scope_terms)
        self.assertEqual(spec.available_values[0].source_ref, "$ctx$.account.ACCT_ID")
```

- [ ] **Step 2: Run the focused test and verify missing contracts fail**

```powershell
python -m unittest tests.test_naming_sql_selector.DataAccessSpecGeneratorTest -v
```

Expected: import errors for the new contracts.

- [ ] **Step 3: Add MVP request/spec contracts**

Extend `models.py` with:

```python
class AvailableValue(SelectorModel):
    name: str
    source_ref: str
    data_type: str = ""
    semantic_tags: list[str] = Field(default_factory=list)


class DataAccessSpec(SelectorModel):
    requires_naming_sql: bool = False
    business_terms: list[str] = Field(default_factory=list)
    scope_terms: list[str] = Field(default_factory=list)
    bo_hints: list[str] = Field(default_factory=list)
    filter_requirements: list[str] = Field(default_factory=list)
    available_values: list[AvailableValue] = Field(default_factory=list)
    allow_full_table: bool = False


class NamingSqlSelectionRequest(SelectorModel):
    site_id: str
    query: str
    node: dict[str, Any] = Field(default_factory=dict)
    parent_node: dict[str, Any] | None = None
    structured_spec: dict[str, Any] = Field(default_factory=dict)
    bo_name: str | None = None
    available_context: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 4: Implement the bounded knowledge interface**

In `knowledge.py`, define `DevelopmentKnowledge`, a `DevelopmentKnowledgeRetriever` protocol, `NoOpDevelopmentKnowledgeRetriever`, and a deterministic test implementation. The static retriever tokenizes the query and returns at most five entries sharing normalized terms; it never creates resource objects.

```python
class DevelopmentKnowledge(BaseModel):
    text: str
    bo_names: list[str] = Field(default_factory=list)
    naming_sql_names: list[str] = Field(default_factory=list)
    semantic_tags: list[str] = Field(default_factory=list)
    param_aliases: dict[str, list[str]] = Field(default_factory=dict)
```

- [ ] **Step 5: Implement deterministic DataAccessSpec generation**

`DataAccessSpecGenerator.generate()` must:

1. Read `structured_spec.requires_naming_sql` first.
2. Infer `True` only when that field is absent and normalized text contains lookup/datasource terms such as `查表`, `查询表`, `datasource`, `naming sql`, or `namingsql`.
3. Merge explicit `business_terms`, `scope_terms`, `bo_hints`, `filter_requirements`, and `allow_full_table` from the structured spec.
4. Add loaded-context values as `AvailableValue` objects and derive `semantic_tags` from each value name and source path.
5. Retrieve at most five knowledge entries and merge their BO names and semantic tags.
6. Deduplicate while preserving first occurrence.

- [ ] **Step 6: Run specification tests**

```powershell
python -m unittest tests.test_naming_sql_selector.DataAccessSpecGeneratorTest -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit session-spec generation**

```powershell
git add agent/naming_sql_selector tests/test_naming_sql_selector.py
git commit -m "feat: generate naming sql access specs"
```

### Task 4: Resolve Exactly One BO

**Files:**
- Modify: `agent/naming_sql_selector/models.py`
- Create: `agent/naming_sql_selector/selector.py`
- Modify: `tests/test_naming_sql_selector.py`

- [ ] **Step 1: Write failing BO resolution tests**

Add these fixture helpers to `tests/test_naming_sql_selector.py` so later selector tests reuse concrete models rather than mocks of domain data:

```python
from agent.naming_sql_selector.models import DataAccessSpec, NamingSqlParamProfile, NamingSqlProfile
from agent.resource_manager.loader.registry_models import BoRegistry, PropertyTerm


def access_spec(**updates):
    values = {
        "requires_naming_sql": True,
        "business_terms": ["ar", "transaction"],
        "scope_terms": ["account"],
        "bo_hints": [],
        "filter_requirements": [],
        "available_values": [],
        "allow_full_table": False,
    }
    values.update(updates)
    return DataAccessSpec.model_validate(values)


def bo_registry_fixture():
    return {
        "BO_AR_TRANS": BoRegistry(
            resource_id="bo.0000",
            bo_name="BO_AR_TRANS",
            bo_desc="AR account transactions",
            property_list=[
                PropertyTerm(
                    field_name="ACCT_ID",
                    description="account id",
                    data_type="key",
                    data_type_name="long",
                )
            ],
        ),
        "BO_FREE_RESOURCE": BoRegistry(
            resource_id="bo.0001",
            bo_name="BO_FREE_RESOURCE",
            bo_desc="subscriber free resource",
            property_list=[],
        ),
    }


def profile_fixture():
    return {
        "BO_AR_TRANS": [
            NamingSqlProfile(
                site_id="site-a",
                bo_name="BO_AR_TRANS",
                naming_sql_id="sql-1",
                sql_name="queryByAcct",
                params=[NamingSqlParamProfile(name="ACCT_ID", data_type="long")],
                filter_fields=["ACCT_ID"],
                scope_tags=["ar", "transaction", "account"],
                is_full_table=False,
                search_text="ar transaction account acct id",
            )
        ],
        "BO_FREE_RESOURCE": [],
    }
```

Then add tests using the two `BoRegistry` objects:

```python
class FakeBoReviewer:
    def __init__(self, selected_bo: str | None):
        self.selected_bo = selected_bo
        self.calls = []

    def review(self, *, spec, candidates):
        self.calls.append(candidates)
        return self.selected_bo


def test_explicit_bo_is_used_without_review(self):
    result = BoResolver().resolve(
        explicit_bo="BO_AR_TRANS",
        spec=access_spec(bo_hints=["BO_AR_TRANS"]),
        bo_registry=bo_registry_fixture(),
        profiles=profile_fixture(),
    )
    assert result.bo_name == "BO_AR_TRANS"
    assert result.review_mode == "not_required"


def test_invalid_explicit_bo_fails_fast(self):
    with self.assertRaisesRegex(ValueError, "BO_NOT_LOADED"):
        BoResolver().resolve(
            explicit_bo="MISSING_BO",
            spec=access_spec(),
            bo_registry=bo_registry_fixture(),
            profiles=profile_fixture(),
        )


def test_invalid_reviewer_choice_falls_back_to_programmatic_top1(self):
    reviewer = FakeBoReviewer("INVENTED_BO")
    result = BoResolver(reviewer=reviewer).resolve(
        explicit_bo=None,
        spec=access_spec(bo_hints=["BO_AR_TRANS"]),
        bo_registry=bo_registry_fixture(),
        profiles=profile_fixture(),
    )
    assert result.bo_name == "BO_AR_TRANS"
    assert result.review_mode == "deterministic_fallback"
```

- [ ] **Step 2: Run BO tests and verify missing resolver failure**

```powershell
python -m unittest tests.test_naming_sql_selector.BoResolverTest -v
```

Expected: import or name failure for `BoResolver`.

- [ ] **Step 3: Implement deterministic BO recall and reviewer validation**

Add `BoResolution(bo_name, review_mode, reasons)` and `BoCandidate(bo_name, score, summary)` models. `BoResolver` builds normalized query terms from the spec, scores BO name/description/property names plus aggregated profile search text, sorts by `(-score, bo_name)`, and sends only top five candidates to the reviewer. A reviewer result is accepted only when it exactly matches a supplied candidate.

When no BO resources are loaded, raise `ValueError("BO_NOT_LOADED: no BO candidates")`; this is the only impossible-selection case because no valid BO exists to choose.

- [ ] **Step 4: Run selector tests**

```powershell
python -m unittest tests.test_naming_sql_selector -v
```

Expected: all BO and specification tests pass.

- [ ] **Step 5: Commit BO resolution**

```powershell
git add agent/naming_sql_selector tests/test_naming_sql_selector.py
git commit -m "feat: resolve naming sql BO scope"
```

### Task 5: Bind Parameters and Select NamingSQL

**Files:**
- Modify: `agent/naming_sql_selector/models.py`
- Modify: `agent/naming_sql_selector/selector.py`
- Modify: `agent/naming_sql_selector/__init__.py`
- Modify: `tests/test_naming_sql_selector.py`

- [ ] **Step 1: Write failing binding and fallback tests**

Add request and loaded-resource helpers using the Task 4 fixtures:

```python
from dataclasses import replace

from agent.naming_sql_selector.models import NamingSqlSelectionRequest
from agent.resource_manager.loader.registry_models import DomainRegistry
from agent.resource_manager.loader.resource_loader import LoadedResource


def request_fixture(**updates):
    values = {
        "site_id": "site-a",
        "query": "query AR transaction by account",
        "node": {"annotation": "AR transaction"},
        "parent_node": {"annotation": "account detail"},
        "structured_spec": {
            "requires_naming_sql": True,
            "bo_hints": ["BO_AR_TRANS"],
            "filter_requirements": ["ACCT_ID"],
        },
        "bo_name": "BO_AR_TRANS",
        "available_context": [],
    }
    values.update(updates)
    return NamingSqlSelectionRequest.model_validate(values)


def loaded_resource_fixture():
    registry = bo_registry_fixture()
    return LoadedResource(
        context_registry={},
        bo_registry=registry,
        function_registry={},
        edsl_tree={},
        domain_registry=DomainRegistry(bo_domains=list(registry)),
        naming_sql_profiles=profile_fixture(),
    )


def full_table_loaded_resource_fixture():
    loaded = loaded_resource_fixture()
    profile = loaded.naming_sql_profiles["BO_AR_TRANS"][0].model_copy(
        update={
            "naming_sql_id": "sql-all",
            "sql_name": "queryAll",
            "params": [],
            "filter_fields": [],
            "is_full_table": True,
        }
    )
    return replace(loaded, naming_sql_profiles={"BO_AR_TRANS": [profile]})
```

Define `selector_fixture()` as `NamingSqlSelector()` and `full_table_selector_fixture()` as `NamingSqlSelector()`. Then add tests for exact, semantic, ambiguous, unbound, and full-table cases:

```python
def test_selects_scoped_sql_when_all_params_bind(self):
    result = selector_fixture().select(
        request_fixture(
            available_context=[
                {"name": "ACCT_ID", "source_ref": "$ctx$.acct.ACCT_ID", "data_type": "long"}
            ]
        ),
        loaded_resource=loaded_resource_fixture(),
    )

    assert result.status == "selected"
    assert result.selected.sql_name == "queryByAcct"
    assert result.selected.binding_plan.is_complete
    assert result.selected.binding_plan.bindings[0].source_ref == "$ctx$.acct.ACCT_ID"


def test_ambiguous_semantic_binding_rejects_candidate(self):
    result = selector_fixture().select(
        request_fixture(
            available_context=[
                {"name": "account id", "source_ref": "$ctx$.a.ID", "data_type": "long"},
                {"name": "billing account id", "source_ref": "$ctx$.b.ID", "data_type": "long"},
            ]
        ),
        loaded_resource=loaded_resource_fixture(),
    )

    assert result.selected is None
    assert result.rejected_candidates[0].reject_codes == ["PARAM_AMBIGUOUS"]


def test_full_table_sql_is_fallback_only_by_default(self):
    result = full_table_selector_fixture().select(
        request_fixture(),
        loaded_resource=full_table_loaded_resource_fixture(),
    )

    assert result.status == "needs_review"
    assert result.selected is None
    assert result.fallback_candidates[0].reason == "FULL_TABLE_FALLBACK_ONLY"
```

- [ ] **Step 2: Run focused tests and verify missing selector behavior**

```powershell
python -m unittest tests.test_naming_sql_selector.NamingSqlSelectorTest -v
```

Expected: failures for missing binding/result contracts.

- [ ] **Step 3: Add binding and result contracts**

Extend `models.py` with:

```python
class ParamBinding(SelectorModel):
    param_name: str
    source_ref: str
    confidence: float
    reason: str


class ParamBindingPlan(SelectorModel):
    bindings: list[ParamBinding] = Field(default_factory=list)
    unbound_params: list[str] = Field(default_factory=list)
    ambiguous_params: list[str] = Field(default_factory=list)
    is_complete: bool = False


class SelectedNamingSql(SelectorModel):
    naming_sql_id: str
    sql_name: str
    score: float
    binding_plan: ParamBindingPlan
    reasons: list[str] = Field(default_factory=list)


class RejectedNamingSql(SelectorModel):
    naming_sql_id: str
    sql_name: str
    reject_codes: list[str]


class FallbackNamingSql(SelectorModel):
    naming_sql_id: str
    sql_name: str
    reason: str


class NamingSqlSelectionResult(SelectorModel):
    status: Literal["selected", "needs_review"]
    selected_bo: str
    selected: SelectedNamingSql | None = None
    fallback_candidates: list[FallbackNamingSql] = Field(default_factory=list)
    rejected_candidates: list[RejectedNamingSql] = Field(default_factory=list)
    review_mode: Literal["llm", "deterministic_fallback", "not_required"]
```

- [ ] **Step 4: Implement binding confidence rules**

Normalize names by removing punctuation and case. Score binding candidates as:

- `1.0`: exact normalized parameter/value name.
- `0.95`: exact alias from retrieved development knowledge.
- `0.85`: semantic-tag overlap plus compatible type.
- `0.0`: no semantic evidence.

Require confidence `>= 0.85`. If two candidates share the highest confidence, mark the parameter ambiguous. If none qualifies, mark it unbound. `is_complete` is true only when both diagnostic lists are empty.

- [ ] **Step 5: Implement candidate filtering and deterministic scoring**

Inside the selected BO:

1. Put every `is_full_table` profile in `fallback_candidates`.
2. Build a binding plan for each scoped profile.
3. Reject incomplete plans with `PARAM_UNBOUND` or `PARAM_AMBIGUOUS`.
4. Reject candidates that do not cover each normalized `filter_requirement` with `FILTER_NOT_COVERED`.
5. Score survivors using bounded components: explicit SQL/knowledge match `40`, filter coverage `25`, average binding confidence `20`, business/scope overlap `10`, other text overlap `5`.
6. Sort by `(-score, sql_name, naming_sql_id)`.
7. Pass at most five survivors to `NamingSqlReviewer`; accept only a supplied NamingSQL ID.
8. On missing/invalid reviewer output, choose programmatic top-1.
9. If no survivor exists and `allow_full_table=true`, select the top deterministic full-table fallback; otherwise return `needs_review`.

- [ ] **Step 6: Implement the standalone facade**

`NamingSqlSelector.select(request, loaded_resource)` performs knowledge retrieval, spec generation, BO resolution, candidate selection, and result creation. It accepts injected retriever/reviewer implementations and defaults to no-op knowledge plus deterministic reviewers. Export the facade and all public request/result models from `__init__.py`.

- [ ] **Step 7: Run all selector tests**

```powershell
python -m unittest tests.test_naming_sql_selector -v
```

Expected: all tests pass without network or a live LLM.

- [ ] **Step 8: Commit standalone selection**

```powershell
git add agent/naming_sql_selector tests/test_naming_sql_selector.py
git commit -m "feat: select bindable naming sql"
```

### Task 6: Constrain Planner Fetches

**Files:**
- Create: `agent/naming_sql_selector/plan_validator.py`
- Modify: `agent/planner/llm_planner.py`
- Modify: `prompt.json`
- Create: `tests/test_naming_sql_plan_validator.py`
- Modify: `tests/test_llm_planner.py`
- Modify: `tests/test_planner_prompt.py`

- [ ] **Step 1: Write failing plan-validator tests**

Create the concrete fixture and plan helper:

```python
from agent.naming_sql_selector.models import (
    NamingSqlSelectionResult,
    ParamBinding,
    ParamBindingPlan,
    SelectedNamingSql,
)


def selected_result_fixture():
    return NamingSqlSelectionResult(
        status="selected",
        selected_bo="BO_AR_TRANS",
        selected=SelectedNamingSql(
            naming_sql_id="sql-1",
            sql_name="queryByAcct",
            score=100.0,
            binding_plan=ParamBindingPlan(
                bindings=[
                    ParamBinding(
                        param_name="ACCT_ID",
                        source_ref="$ctx$.acct.ACCT_ID",
                        confidence=1.0,
                        reason="exact normalized name",
                    )
                ],
                is_complete=True,
            ),
        ),
        review_mode="not_required",
    )


def fetch_plan(name: str, path: str):
    return {
        "nodes": [
            {
                "type": "return",
                "value": {
                    "type": "fetch_one",
                    "name": name,
                    "params": [
                        {
                            "name": "ACCT_ID",
                            "value": {"type": "context_path", "path": path},
                        }
                    ],
                },
            }
        ]
    }
```

Then add tests with a valid fetch, wrong SQL name, missing parameter, and changed context path:

```python
class NamingSqlPlanValidatorTest(unittest.TestCase):
    def test_accepts_exact_selected_sql_and_bindings(self):
        validate_naming_sql_plan(
            Plan.model_validate(fetch_plan("queryByAcct", "$ctx$.acct.ACCT_ID")),
            selected_result_fixture(),
        )

    def test_rejects_planner_reselection(self):
        with self.assertRaisesRegex(ValueError, "NAMING_SQL_RESELECTED"):
            validate_naming_sql_plan(
                Plan.model_validate(fetch_plan("queryAll", "$ctx$.acct.ACCT_ID")),
                selected_result_fixture(),
            )

    def test_rejects_parameter_rebinding(self):
        with self.assertRaisesRegex(ValueError, "NAMING_SQL_BINDING_CHANGED"):
            validate_naming_sql_plan(
                Plan.model_validate(fetch_plan("queryByAcct", "$ctx$.other.ID")),
                selected_result_fixture(),
            )
```

- [ ] **Step 2: Run validator tests and verify the missing module fails**

```powershell
python -m unittest tests.test_naming_sql_plan_validator -v
```

Expected: import failure for `plan_validator`.

- [ ] **Step 3: Implement recursive plan validation**

Walk every Pydantic plan node recursively. For each `fetch` or `fetch_one`, require:

- `name == result.selected.sql_name`;
- parameter-name set equals the binding plan parameter-name set;
- each bound value is a `ContextPathExprPlanNode` whose path equals `source_ref`.

Raise `NAMING_SQL_RESELECTED`, `NAMING_SQL_PARAM_SET_CHANGED`, or `NAMING_SQL_BINDING_CHANGED` with the offending SQL or parameter name. If result has no selection, raise `NAMING_SQL_REVIEW_REQUIRED` before walking.

- [ ] **Step 4: Add selected-SQL summary tests**

In `tests/test_llm_planner.py`, call `_summarize_filtered_environment()` with an environment carrying a selection and assert that the serialized resources contain exactly one NamingSQL plus its fixed bindings. Assert no sibling NamingSQL appears.

- [ ] **Step 5: Extend planner summary and prompt contract**

Add an optional `naming_sql_selection` field to `FilteredEnvironment`. In `_summarize_filtered_environment()`, emit:

```python
"naming_sql_selection": {
    "bo": selection.selected_bo,
    "name": selection.selected.sql_name,
    "bindings": [
        {
            "name": binding.param_name,
            "source_ref": binding.source_ref,
        }
        for binding in selection.selected.binding_plan.bindings
    ],
}
```

Update planner and repair prompts to state that this SQL name and every binding must be copied verbatim, and that no other NamingSQL may be selected.

- [ ] **Step 6: Run planner and prompt tests**

```powershell
python -m unittest tests.test_naming_sql_plan_validator tests.test_llm_planner tests.test_planner_prompt -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit planner constraints**

```powershell
git add agent/naming_sql_selector/plan_validator.py agent/planner/llm_planner.py agent/environment/environment.py prompt.json tests/test_naming_sql_plan_validator.py tests/test_llm_planner.py tests/test_planner_prompt.py
git commit -m "feat: constrain planner to selected naming sql"
```

### Task 7: Integrate the Selector Route into Expression Generation

**Files:**
- Modify: `agent/models.py`
- Modify: `agent/value_logic_generator.py`
- Modify: `tests/test_value_logic_generator.py`

- [ ] **Step 1: Write failing route and integration tests**

Add a fake selector that records calls and returns a selected result. Add tests proving:

```python
def test_structured_false_skips_naming_sql_selector(self):
    generator = generator_with_failing_selector()
    generator.generate(request_fixture(structured_spec={"requires_naming_sql": False}))


def test_structured_true_uses_selector_and_narrows_planner_environment(self):
    selector = FakeNamingSqlSelector(selected_result_fixture())
    planner = FetchPlanner("queryByAcct", "$ctx$.acct.ACCT_ID")
    generator = ValueLogicGenerator(
        resource_loader=resource_loader_fixture(),
        naming_sql_selector=selector,
        llm_planner=planner,
        resource_filter_target_generator=target_generator_fixture(),
    )

    result = generator.generate(
        request_fixture(structured_spec={"requires_naming_sql": True})
    )

    assert selector.calls
    assert planner.calls[0]["filtered_env"].naming_sql_selection.selected.sql_name == "queryByAcct"
    assert [item.sql_name for item in planner.calls[0]["filtered_env"].selected_bos[0].naming_sql_list] == ["queryByAcct"]
    assert result.expression == "fetch_one(queryByAcct, ACCT_ID: $ctx$.acct.ACCT_ID)"


def test_needs_review_stops_before_planner(self):
    with self.assertRaisesRegex(ValueError, "NAMING_SQL_REVIEW_REQUIRED"):
        generator_with_review_required_selector().generate(
            request_fixture(structured_spec={"requires_naming_sql": True})
        )
```

- [ ] **Step 2: Run the new integration tests and verify route failures**

```powershell
python -m unittest tests.test_value_logic_generator -v
```

Expected: failures for the missing request field and selector dependency.

- [ ] **Step 3: Add the structured specification field**

Extend `ValueLogicRequest` with:

```python
structured_spec: dict[str, Any] = Field(default_factory=dict)
```

This is backward compatible with all existing callers.

- [ ] **Step 4: Add selector dependency and route helper**

Inject `naming_sql_selector: NamingSqlSelector | None = None` into `ValueLogicGenerator`. Add `_requires_naming_sql(request, expression_spec)` that returns the explicit boolean when present and otherwise invokes the same compatibility term check used by `DataAccessSpecGenerator`.

- [ ] **Step 5: Build the standalone request and narrow resources**

On the NamingSQL route:

1. Collect all global contexts and currently visible local contexts into compact `{name, source_ref, data_type, semantic_tags}` dictionaries.
2. Call `selector.select()` with the already loaded resources.
3. Raise `ValueError("NAMING_SQL_REVIEW_REQUIRED")` when selected is null.
4. Clone the selected `BoRegistry` with only the selected `NamingSqlDefTerm`.
5. Add contexts referenced by the binding plan to the filtered environment if normal filtering omitted them.
6. Store the selection on `FilteredEnvironment.naming_sql_selection`.
7. Call the existing planner.
8. Run `validate_naming_sql_plan()` before AST construction.

The non-NamingSQL branch remains byte-for-byte equivalent except for calling the route helper.

- [ ] **Step 6: Run expression and operation regression tests**

```powershell
python -m unittest tests.test_value_logic_generator tests.test_expression_generator tests.test_generate_node_operation tests.test_modify_node_operation -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit expression integration**

```powershell
git add agent/models.py agent/value_logic_generator.py tests/test_value_logic_generator.py
git commit -m "feat: route expressions through naming sql selector"
```

### Task 8: End-to-End Verification and Documentation Alignment

**Files:**
- Modify only if verification exposes a defect in files already listed above.

- [ ] **Step 1: Run the focused NamingSQL suite**

```powershell
python -m unittest tests.test_naming_sql_profile_builder tests.test_naming_sql_selector tests.test_naming_sql_plan_validator tests.test_resource_loader tests.test_llm_planner tests.test_planner_prompt tests.test_value_logic_generator -v
```

Expected: all tests pass with no network access.

- [ ] **Step 2: Run the complete test suite**

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Verify the planner never receives an unbounded NamingSQL list**

Run a manual test fixture containing one BO with at least 101 NamingSQL profiles. Assert the fake planner receives one selected NamingSQL, while the fake reviewer receives at most five compact candidates. Print and inspect these counts:

```text
loaded_profiles=101
review_candidates<=5
planner_naming_sql_count=1
```

- [ ] **Step 4: Check repository cleanliness and diff quality**

```powershell
git diff --check
git status --short
```

Expected: `git diff --check` has no output; status contains only intentional files if a final fix remains.

- [ ] **Step 5: Commit any final verification-only correction**

If Step 1-4 required a correction, stage the implementation and test paths owned by this plan and commit it with:

```powershell
git add agent/naming_sql_selector agent/resource_manager/loader/registry_models.py agent/resource_manager/loader/resource_loader.py agent/environment/environment.py agent/models.py agent/value_logic_generator.py agent/planner/llm_planner.py prompt.json tests/test_naming_sql_profile_builder.py tests/test_naming_sql_selector.py tests/test_naming_sql_plan_validator.py tests/test_resource_loader.py tests/test_value_logic_generator.py tests/test_llm_planner.py tests/test_planner_prompt.py
git commit -m "fix: harden naming sql selector verification"
```

If no correction was required, do not create an empty commit.
