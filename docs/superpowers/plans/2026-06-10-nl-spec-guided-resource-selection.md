# NL Spec Guided Resource Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mock-backed NL Spec stage before resource filtering so usable specs from `region_type + cbs_name` constrain resource selection and planner generation, with current query-driven filtering preserved as fallback.

**Architecture:** Add a focused `agent/nl_spec/` package for spec models, mock knowledge providers, and generation. Add `SpecResourceSelector` in `agent/environment/` to wrap the existing `build_filtered_environment()` path by running constrained selections per `source_type + nl`, then integrate the selector into `ValueLogicGenerator` and pass a compact spec summary into `LLMPlanner`.

**Tech Stack:** Python 3.14, Pydantic models, `unittest`, existing `LLMResourceFilter`, existing `build_filtered_environment()`, existing `prompt.json` prompt manager.

---

## File Structure

- Create `agent/nl_spec/__init__.py`: package exports for `NLSpec`, `ValueSourceCandidate`, `NLSpecGenerator`, mock providers, and diagnostic enums.
- Create `agent/nl_spec/models.py`: Pydantic models for NL Spec, provider records, diagnostics, and validation helpers.
- Create `agent/nl_spec/knowledge.py`: protocol-style provider interfaces plus deterministic mock providers for terms and region experience.
- Create `agent/nl_spec/generator.py`: combines request input, term knowledge, and region experience into an `NLSpec`.
- Create `agent/environment/spec_resource_selector.py`: spec-first resource selector with fallback to current query path.
- Modify `agent/models.py`: add optional `region_type` and `cbs_name` to `ValueLogicRequest`.
- Modify `agent/value_logic_generator.py`: inject `NLSpecGenerator` and `SpecResourceSelector`; replace direct `build_filtered_environment()` call in expression planning.
- Modify `agent/planner/llm_planner.py`: accept optional `nl_spec` and pass `nl_spec_json` to planner and repair prompts.
- Modify `prompt.json`: add `nl_spec` prompt variable guidance to planner and planner_repair prompts.
- Create `tests/test_nl_spec_models.py`: model validation tests.
- Create `tests/test_nl_spec_generator.py`: mock provider and spec generation tests.
- Create `tests/test_spec_resource_selector.py`: selector source-type constraints, fallback, path diagnostics, and merge tests.
- Modify `tests/test_value_logic_generator.py`: verify integration and old fallback behavior.
- Modify `tests/test_llm_planner.py`: verify planner receives spec summary.
- Modify `tests/test_planner_prompt.py`: verify prompt hard-boundary language.

## Task 1: Request And NL Spec Models

**Files:**
- Modify: `D:\workspace\edsl_generation\agent\models.py`
- Create: `D:\workspace\edsl_generation\agent\nl_spec\__init__.py`
- Create: `D:\workspace\edsl_generation\agent\nl_spec\models.py`
- Test: `D:\workspace\edsl_generation\tests\test_nl_spec_models.py`

- [ ] **Step 1: Write failing tests for request compatibility and NL Spec validation**

Add `tests/test_nl_spec_models.py`:

```python
import unittest

from pydantic import ValidationError

from agent.models import ValueLogicRequest
from agent.nl_spec.models import (
    FALLBACK_MISSING_SPEC_INPUT,
    NLSpec,
    SelectorDiagnostics,
    SelectionPath,
    ValueSourceCandidate,
)


class NLSpecModelsTest(unittest.TestCase):
    def test_value_logic_request_accepts_optional_spec_inputs(self):
        request = ValueLogicRequest(
            site_id="site1",
            project_id="project1",
            node_path="$.mapping_content.children[1]",
            node={"node_id": "node-1"},
            query="取账户余额",
            region_type="basic_info",
            cbs_name="账户余额",
        )

        self.assertEqual(request.region_type, "basic_info")
        self.assertEqual(request.cbs_name, "账户余额")

    def test_value_logic_request_keeps_old_call_shape(self):
        request = ValueLogicRequest(
            site_id="site1",
            project_id="project1",
            node_path="$.mapping_content.children[1]",
            node={"node_id": "node-1"},
            query="query one prep sub by id",
        )

        self.assertIsNone(request.region_type)
        self.assertIsNone(request.cbs_name)

    def test_nl_spec_requires_source_candidates(self):
        with self.assertRaises(ValidationError):
            NLSpec(
                concept_id="cbs.account.balance",
                concept_name="账户余额",
                semantic_type="amount",
                region_type="basic_info",
                value_source_candidates=[],
                evidence=["term:账户余额"],
                needs_business_knowledge=False,
            )

    def test_nl_spec_summarizes_business_knowledge(self):
        spec = NLSpec(
            concept_id="cbs.account.balance",
            concept_name="账户余额",
            semantic_type="amount",
            region_type="basic_info",
            value_source_candidates=[
                ValueSourceCandidate(
                    source_type="context",
                    nl="优先从账单上下文或账户上下文中获取账户余额。",
                )
            ],
            evidence=["term:账户余额", "region_experience:basic_info.账户余额"],
            needs_business_knowledge=False,
        )

        self.assertEqual(
            spec.to_planner_summary()["value_source_candidates"][0]["source_type"],
            "context",
        )
        self.assertIn("账户余额", spec.to_search_text())

    def test_selector_diagnostics_records_fallback_reason(self):
        diagnostics = SelectorDiagnostics(
            path=SelectionPath.QUERY_FALLBACK,
            fallback_reason=FALLBACK_MISSING_SPEC_INPUT,
        )

        self.assertEqual(diagnostics.path, SelectionPath.QUERY_FALLBACK)
        self.assertEqual(diagnostics.fallback_reason, FALLBACK_MISSING_SPEC_INPUT)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.test_nl_spec_models
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent.nl_spec'` or missing `region_type` / `cbs_name` fields.

- [ ] **Step 3: Add optional request fields**

Modify `agent/models.py` so `ValueLogicRequest` becomes:

```python
class ValueLogicRequest(BaseModel):
    site_id: str
    project_id: str
    node_path: str
    node: dict[str, Any]
    parent_node: dict[str, Any] | None = None
    query: str
    region_type: str | None = None
    cbs_name: str | None = None
    is_ab: bool = False
    edsl_tree: dict[str, Any] | None = None
```

- [ ] **Step 4: Add NL Spec model package**

Create `agent/nl_spec/__init__.py`:

```python
from agent.nl_spec.models import (
    FALLBACK_INVALID_SPEC,
    FALLBACK_MISSING_SPEC_INPUT,
    FALLBACK_NO_SPEC_RESOURCES,
    NLSpec,
    SelectorDiagnostics,
    SelectionPath,
    ValueSourceCandidate,
)

__all__ = [
    "FALLBACK_INVALID_SPEC",
    "FALLBACK_MISSING_SPEC_INPUT",
    "FALLBACK_NO_SPEC_RESOURCES",
    "NLSpec",
    "SelectorDiagnostics",
    "SelectionPath",
    "ValueSourceCandidate",
]
```

Create `agent/nl_spec/models.py`:

```python
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


SpecSourceType = Literal["context", "bo_field", "naming_sql", "function"]

FALLBACK_MISSING_SPEC_INPUT = "missing_spec_input"
FALLBACK_INVALID_SPEC = "invalid_spec"
FALLBACK_NO_SPEC_RESOURCES = "no_spec_resources"


class SelectionPath(StrEnum):
    SPEC_GUIDED = "spec_guided"
    QUERY_FALLBACK = "query_fallback"


class ValueSourceCandidate(BaseModel):
    source_type: SpecSourceType
    nl: str = Field(min_length=1)

    def to_summary(self) -> dict[str, str]:
        return {
            "source_type": self.source_type,
            "nl": self.nl,
        }


class NLSpec(BaseModel):
    concept_id: str = Field(min_length=1)
    concept_name: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)
    region_type: str = Field(min_length=1)
    value_source_candidates: list[ValueSourceCandidate] = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    needs_business_knowledge: bool = False

    def to_search_text(self) -> str:
        candidate_text = " ".join(candidate.nl for candidate in self.value_source_candidates)
        evidence_text = " ".join(self.evidence)
        return " ".join(
            part
            for part in (
                self.concept_id,
                self.concept_name,
                self.semantic_type,
                self.region_type,
                candidate_text,
                evidence_text,
            )
            if part
        )

    def to_planner_summary(self) -> dict[str, object]:
        return {
            "concept_id": self.concept_id,
            "concept_name": self.concept_name,
            "semantic_type": self.semantic_type,
            "region_type": self.region_type,
            "value_source_candidates": [
                candidate.to_summary() for candidate in self.value_source_candidates
            ],
            "evidence": list(self.evidence),
            "needs_business_knowledge": self.needs_business_knowledge,
        }


class SelectorDiagnostics(BaseModel):
    path: SelectionPath
    fallback_reason: str | None = None
    concept_id: str | None = None
    concept_name: str | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python -m unittest tests.test_nl_spec_models
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add agent/models.py agent/nl_spec/__init__.py agent/nl_spec/models.py tests/test_nl_spec_models.py
git commit -m "feat: add nl spec request and models"
```

## Task 2: Mock Knowledge Providers And NL Spec Generator

**Files:**
- Modify: `D:\workspace\edsl_generation\agent\nl_spec\__init__.py`
- Create: `D:\workspace\edsl_generation\agent\nl_spec\knowledge.py`
- Create: `D:\workspace\edsl_generation\agent\nl_spec\generator.py`
- Test: `D:\workspace\edsl_generation\tests\test_nl_spec_generator.py`

- [ ] **Step 1: Write failing generator tests**

Add `tests/test_nl_spec_generator.py`:

```python
import unittest

from agent.models import NodeDef
from agent.nl_spec.generator import NLSpecGenerator
from agent.nl_spec.knowledge import MockRegionExperienceProvider, MockTermProvider


class NLSpecGeneratorTest(unittest.TestCase):
    def test_generates_account_balance_spec_from_mock_knowledge(self):
        generator = NLSpecGenerator(
            term_provider=MockTermProvider(
                {
                    ("site1", "project1", "账户余额"): {
                        "concept_id": "cbs.account.balance",
                        "concept_name": "账户余额",
                        "semantic_type": "amount",
                    }
                }
            ),
            experience_provider=MockRegionExperienceProvider(
                {
                    ("site1", "project1", "basic_info"): {
                        "账户余额": [
                            {
                                "source_type": "context",
                                "nl": "优先从账单上下文或账户上下文中获取账户余额。",
                            },
                            {
                                "source_type": "bo_field",
                                "nl": "如上下文中没有账户余额，可从账户余额相关 BO 中查询，查询条件通常包括账户 ID、账期 ID，返回余额字段。",
                            },
                            {
                                "source_type": "naming_sql",
                                "nl": "如项目中存在账户余额查询类 namingSQL，可使用账户 ID 和账期作为入参，返回账户余额。",
                            },
                        ]
                    }
                }
            ),
        )

        spec = generator.generate(
            site_id="site1",
            project_id="project1",
            region_type="basic_info",
            cbs_name="账户余额",
            query="取账户余额",
            node_info=NodeDef(
                node_id="node-1",
                node_path="$.mapping_content.children[1]",
                node_name="ACCT_BALANCE",
            ),
        )

        self.assertIsNotNone(spec)
        self.assertEqual(spec.concept_id, "cbs.account.balance")
        self.assertEqual(spec.concept_name, "账户余额")
        self.assertEqual(spec.semantic_type, "amount")
        self.assertEqual(spec.region_type, "basic_info")
        self.assertEqual(
            [candidate.source_type for candidate in spec.value_source_candidates],
            ["context", "bo_field", "naming_sql"],
        )
        self.assertIn("term:账户余额", spec.evidence)
        self.assertIn("region_experience:basic_info.账户余额", spec.evidence)

    def test_returns_none_when_region_type_or_cbs_name_is_missing(self):
        generator = NLSpecGenerator(
            term_provider=MockTermProvider({}),
            experience_provider=MockRegionExperienceProvider({}),
        )

        self.assertIsNone(
            generator.generate(
                site_id="site1",
                project_id="project1",
                region_type=None,
                cbs_name="账户余额",
                query="取账户余额",
                node_info=NodeDef(node_id="node-1", node_path="/Node", node_name="Node"),
            )
        )
        self.assertIsNone(
            generator.generate(
                site_id="site1",
                project_id="project1",
                region_type="basic_info",
                cbs_name=None,
                query="取账户余额",
                node_info=NodeDef(node_id="node-1", node_path="/Node", node_name="Node"),
            )
        )

    def test_returns_none_when_mock_knowledge_has_no_match(self):
        generator = NLSpecGenerator(
            term_provider=MockTermProvider({}),
            experience_provider=MockRegionExperienceProvider({}),
        )

        spec = generator.generate(
            site_id="site1",
            project_id="project1",
            region_type="basic_info",
            cbs_name="账户余额",
            query="取账户余额",
            node_info=NodeDef(node_id="node-1", node_path="/Node", node_name="Node"),
        )

        self.assertIsNone(spec)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.test_nl_spec_generator
```

Expected: FAIL with missing `agent.nl_spec.generator` and `agent.nl_spec.knowledge`.

- [ ] **Step 3: Implement mock knowledge providers**

Create `agent/nl_spec/knowledge.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol


class TermProvider(Protocol):
    def get_term(self, *, site_id: str, project_id: str, cbs_name: str) -> dict[str, str] | None:
        raise NotImplementedError


class RegionExperienceProvider(Protocol):
    def get_experience(
        self,
        *,
        site_id: str,
        project_id: str,
        region_type: str,
        cbs_name: str,
    ) -> list[dict[str, str]]:
        raise NotImplementedError


@dataclass(slots=True)
class MockTermProvider:
    terms: Mapping[tuple[str, str, str], dict[str, str]] = field(default_factory=dict)

    def get_term(self, *, site_id: str, project_id: str, cbs_name: str) -> dict[str, str] | None:
        value = self.terms.get((site_id, project_id, cbs_name))
        if value is None:
            return None
        return dict(value)


@dataclass(slots=True)
class MockRegionExperienceProvider:
    experiences: Mapping[tuple[str, str, str], Mapping[str, list[dict[str, str]]]] = field(default_factory=dict)

    def get_experience(
        self,
        *,
        site_id: str,
        project_id: str,
        region_type: str,
        cbs_name: str,
    ) -> list[dict[str, str]]:
        region_items = self.experiences.get((site_id, project_id, region_type), {})
        return [dict(item) for item in region_items.get(cbs_name, [])]
```

- [ ] **Step 4: Implement deterministic NL Spec generator**

Create `agent/nl_spec/generator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from agent.models import NodeDef
from agent.nl_spec.knowledge import MockRegionExperienceProvider, MockTermProvider, RegionExperienceProvider, TermProvider
from agent.nl_spec.models import NLSpec, ValueSourceCandidate


@dataclass(slots=True)
class NLSpecGenerator:
    term_provider: TermProvider | None = None
    experience_provider: RegionExperienceProvider | None = None

    def __post_init__(self) -> None:
        if self.term_provider is None:
            self.term_provider = MockTermProvider({})
        if self.experience_provider is None:
            self.experience_provider = MockRegionExperienceProvider({})

    def generate(
        self,
        *,
        site_id: str,
        project_id: str,
        region_type: str | None,
        cbs_name: str | None,
        query: str,
        node_info: NodeDef,
    ) -> NLSpec | None:
        if not region_type or not cbs_name:
            return None

        term = self.term_provider.get_term(
            site_id=site_id,
            project_id=project_id,
            cbs_name=cbs_name,
        )
        experiences = self.experience_provider.get_experience(
            site_id=site_id,
            project_id=project_id,
            region_type=region_type,
            cbs_name=cbs_name,
        )
        if term is None or not experiences:
            return None

        try:
            return NLSpec(
                concept_id=term.get("concept_id") or f"cbs.{cbs_name}",
                concept_name=term.get("concept_name") or cbs_name,
                semantic_type=term.get("semantic_type") or "unknown",
                region_type=region_type,
                value_source_candidates=[
                    ValueSourceCandidate(
                        source_type=str(item.get("source_type") or ""),
                        nl=str(item.get("nl") or ""),
                    )
                    for item in experiences
                ],
                evidence=[
                    f"term:{cbs_name}",
                    f"region_experience:{region_type}.{cbs_name}",
                ],
                needs_business_knowledge=False,
            )
        except ValidationError:
            return None
```

- [ ] **Step 5: Export generator and providers**

Modify `agent/nl_spec/__init__.py`:

```python
from agent.nl_spec.generator import NLSpecGenerator
from agent.nl_spec.knowledge import MockRegionExperienceProvider, MockTermProvider, RegionExperienceProvider, TermProvider
from agent.nl_spec.models import (
    FALLBACK_INVALID_SPEC,
    FALLBACK_MISSING_SPEC_INPUT,
    FALLBACK_NO_SPEC_RESOURCES,
    NLSpec,
    SelectorDiagnostics,
    SelectionPath,
    ValueSourceCandidate,
)

__all__ = [
    "FALLBACK_INVALID_SPEC",
    "FALLBACK_MISSING_SPEC_INPUT",
    "FALLBACK_NO_SPEC_RESOURCES",
    "MockRegionExperienceProvider",
    "MockTermProvider",
    "NLSpec",
    "NLSpecGenerator",
    "RegionExperienceProvider",
    "SelectorDiagnostics",
    "SelectionPath",
    "TermProvider",
    "ValueSourceCandidate",
]
```

- [ ] **Step 6: Run generator tests**

Run:

```bash
python -m unittest tests.test_nl_spec_generator tests.test_nl_spec_models
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add agent/nl_spec/__init__.py agent/nl_spec/knowledge.py agent/nl_spec/generator.py tests/test_nl_spec_generator.py
git commit -m "feat: add mock-backed nl spec generator"
```

## Task 3: SpecResourceSelector

**Files:**
- Create: `D:\workspace\edsl_generation\agent\environment\spec_resource_selector.py`
- Test: `D:\workspace\edsl_generation\tests\test_spec_resource_selector.py`

- [ ] **Step 1: Write failing selector tests**

Add `tests/test_spec_resource_selector.py`:

```python
import unittest

from agent.environment.environment import FilteredEnvironment
from agent.environment.spec_resource_selector import SpecResourceSelector
from agent.models import NodeDef
from agent.nl_spec.models import (
    FALLBACK_INVALID_SPEC,
    FALLBACK_MISSING_SPEC_INPUT,
    FALLBACK_NO_SPEC_RESOURCES,
    NLSpec,
    SelectionPath,
    ValueSourceCandidate,
)


class Resource:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class FakeSpecGenerator:
    def __init__(self, spec):
        self.spec = spec
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.spec


class FakeEnvironmentBuilder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class SpecResourceSelectorTest(unittest.TestCase):
    def test_context_candidate_only_searches_context_groups(self):
        spec = NLSpec(
            concept_id="cbs.account.balance",
            concept_name="账户余额",
            semantic_type="amount",
            region_type="basic_info",
            value_source_candidates=[
                ValueSourceCandidate(source_type="context", nl="优先从账单上下文获取账户余额。")
            ],
            evidence=["term:账户余额"],
        )
        builder = FakeEnvironmentBuilder(
            [
                FilteredEnvironment(
                    selected_global_contexts=[Resource(resource_id="ctx.1")],
                    selected_global_context_ids=["ctx.1"],
                )
            ]
        )
        selector = SpecResourceSelector(
            spec_generator=FakeSpecGenerator(spec),
            environment_builder=builder,
        )

        result = selector.select(
            node_info=_node_info(),
            user_query="取账户余额 and use DacsDataTrans.CustCallMask",
            site_id="site1",
            project_id="project1",
            region_type="basic_info",
            cbs_name="账户余额",
            registry=Resource(),
            fallback_limits=_limits(),
            llm_resource_filter=Resource(),
        )

        self.assertEqual(result.diagnostics.path, SelectionPath.SPEC_GUIDED)
        self.assertEqual(builder.calls[0]["top_global_context"], 5)
        self.assertEqual(builder.calls[0]["top_local_context"], 5)
        self.assertEqual(builder.calls[0]["top_bo"], 0)
        self.assertEqual(builder.calls[0]["top_function"], 0)
        self.assertIn("账单上下文", builder.calls[0]["user_query"])

    def test_bo_candidate_does_not_search_functions(self):
        spec = NLSpec(
            concept_id="cbs.account.balance",
            concept_name="账户余额",
            semantic_type="amount",
            region_type="basic_info",
            value_source_candidates=[
                ValueSourceCandidate(source_type="bo_field", nl="从账户余额相关 BO 中查询余额字段。")
            ],
            evidence=["term:账户余额"],
        )
        builder = FakeEnvironmentBuilder(
            [
                FilteredEnvironment(
                    selected_bos=[Resource(resource_id="bo.1")],
                    selected_bo_ids=["bo.1"],
                )
            ]
        )
        selector = SpecResourceSelector(
            spec_generator=FakeSpecGenerator(spec),
            environment_builder=builder,
        )

        result = selector.select(
            node_info=_node_info(),
            user_query="取账户余额 mask phone",
            site_id="site1",
            project_id="project1",
            region_type="basic_info",
            cbs_name="账户余额",
            registry=Resource(),
            fallback_limits=_limits(),
            llm_resource_filter=Resource(),
        )

        self.assertEqual(result.diagnostics.path, SelectionPath.SPEC_GUIDED)
        self.assertEqual(builder.calls[0]["top_bo"], 5)
        self.assertEqual(builder.calls[0]["top_function"], 0)

    def test_missing_spec_input_falls_back_to_query_path(self):
        builder = FakeEnvironmentBuilder(
            [
                FilteredEnvironment(
                    selected_functions=[Resource(resource_id="func.1")],
                    selected_function_ids=["func.1"],
                )
            ]
        )
        selector = SpecResourceSelector(
            spec_generator=FakeSpecGenerator(None),
            environment_builder=builder,
        )

        result = selector.select(
            node_info=_node_info(),
            user_query="mask phone",
            site_id="site1",
            project_id="project1",
            region_type=None,
            cbs_name="账户余额",
            registry=Resource(),
            fallback_limits=_limits(),
            llm_resource_filter=Resource(),
        )

        self.assertEqual(result.diagnostics.path, SelectionPath.QUERY_FALLBACK)
        self.assertEqual(result.diagnostics.fallback_reason, FALLBACK_MISSING_SPEC_INPUT)
        self.assertEqual(builder.calls[0]["user_query"], "mask phone")
        self.assertEqual(builder.calls[0]["top_function"], 5)

    def test_invalid_spec_falls_back_to_query_path(self):
        builder = FakeEnvironmentBuilder([FilteredEnvironment()])
        selector = SpecResourceSelector(
            spec_generator=FakeSpecGenerator(None),
            environment_builder=builder,
        )

        result = selector.select(
            node_info=_node_info(),
            user_query="取账户余额",
            site_id="site1",
            project_id="project1",
            region_type="basic_info",
            cbs_name="账户余额",
            registry=Resource(),
            fallback_limits=_limits(),
            llm_resource_filter=Resource(),
        )

        self.assertEqual(result.diagnostics.path, SelectionPath.QUERY_FALLBACK)
        self.assertEqual(result.diagnostics.fallback_reason, FALLBACK_INVALID_SPEC)

    def test_empty_spec_resources_falls_back_to_query_path(self):
        spec = NLSpec(
            concept_id="cbs.account.balance",
            concept_name="账户余额",
            semantic_type="amount",
            region_type="basic_info",
            value_source_candidates=[
                ValueSourceCandidate(source_type="context", nl="优先从上下文取账户余额。")
            ],
            evidence=["term:账户余额"],
        )
        builder = FakeEnvironmentBuilder(
            [
                FilteredEnvironment(),
                FilteredEnvironment(
                    selected_bos=[Resource(resource_id="bo.1")],
                    selected_bo_ids=["bo.1"],
                ),
            ]
        )
        selector = SpecResourceSelector(
            spec_generator=FakeSpecGenerator(spec),
            environment_builder=builder,
        )

        result = selector.select(
            node_info=_node_info(),
            user_query="lookup balance BO",
            site_id="site1",
            project_id="project1",
            region_type="basic_info",
            cbs_name="账户余额",
            registry=Resource(),
            fallback_limits=_limits(),
            llm_resource_filter=Resource(),
        )

        self.assertEqual(result.diagnostics.path, SelectionPath.QUERY_FALLBACK)
        self.assertEqual(result.diagnostics.fallback_reason, FALLBACK_NO_SPEC_RESOURCES)
        self.assertEqual(len(builder.calls), 2)
        self.assertEqual(result.filtered_env.selected_bo_ids, ["bo.1"])


def _node_info():
    return NodeDef(node_id="node-1", node_path="/Node", node_name="Node")


def _limits():
    return {
        "top_global_context": 5,
        "top_local_context": 5,
        "top_bo": 5,
        "top_function": 5,
    }


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run selector tests to verify they fail**

Run:

```bash
python -m unittest tests.test_spec_resource_selector
```

Expected: FAIL with missing `agent.environment.spec_resource_selector`.

- [ ] **Step 3: Implement selector result and source-type limits**

Create `agent/environment/spec_resource_selector.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.environment.environment import FilteredEnvironment, build_filtered_environment
from agent.models import NodeDef
from agent.nl_spec.generator import NLSpecGenerator
from agent.nl_spec.models import (
    FALLBACK_INVALID_SPEC,
    FALLBACK_MISSING_SPEC_INPUT,
    FALLBACK_NO_SPEC_RESOURCES,
    NLSpec,
    SelectorDiagnostics,
    SelectionPath,
)


@dataclass(slots=True)
class SpecSelectionResult:
    filtered_env: FilteredEnvironment
    diagnostics: SelectorDiagnostics
    nl_spec: NLSpec | None = None


class SpecResourceSelector:
    def __init__(
        self,
        *,
        spec_generator: NLSpecGenerator | None = None,
        environment_builder: Callable[..., FilteredEnvironment] = build_filtered_environment,
    ):
        self.spec_generator = spec_generator or NLSpecGenerator()
        self.environment_builder = environment_builder

    def select(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        site_id: str,
        project_id: str,
        region_type: str | None,
        cbs_name: str | None,
        registry: Any,
        fallback_limits: dict[str, int],
        llm_resource_filter: Any | None,
    ) -> SpecSelectionResult:
        if not region_type or not cbs_name:
            return self._fallback(
                node_info=node_info,
                user_query=user_query,
                registry=registry,
                fallback_limits=fallback_limits,
                llm_resource_filter=llm_resource_filter,
                reason=FALLBACK_MISSING_SPEC_INPUT,
            )

        spec = self.spec_generator.generate(
            site_id=site_id,
            project_id=project_id,
            region_type=region_type,
            cbs_name=cbs_name,
            query=user_query,
            node_info=node_info,
        )
        if spec is None:
            return self._fallback(
                node_info=node_info,
                user_query=user_query,
                registry=registry,
                fallback_limits=fallback_limits,
                llm_resource_filter=llm_resource_filter,
                reason=FALLBACK_INVALID_SPEC,
            )

        selected_env = FilteredEnvironment()
        for candidate in spec.value_source_candidates:
            env = self.environment_builder(
                node_info=node_info,
                user_query=_candidate_search_text(spec, candidate.nl),
                registry=registry,
                llm_resource_filter=llm_resource_filter,
                **_limits_for_source_type(candidate.source_type, fallback_limits),
            )
            selected_env = _merge_filtered_environments(selected_env, env, fallback_limits)

        if not _has_any_selected_resource(selected_env):
            return self._fallback(
                node_info=node_info,
                user_query=user_query,
                registry=registry,
                fallback_limits=fallback_limits,
                llm_resource_filter=llm_resource_filter,
                reason=FALLBACK_NO_SPEC_RESOURCES,
            )

        return SpecSelectionResult(
            filtered_env=selected_env,
            diagnostics=SelectorDiagnostics(
                path=SelectionPath.SPEC_GUIDED,
                concept_id=spec.concept_id,
                concept_name=spec.concept_name,
            ),
            nl_spec=spec,
        )

    def _fallback(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        registry: Any,
        fallback_limits: dict[str, int],
        llm_resource_filter: Any | None,
        reason: str,
    ) -> SpecSelectionResult:
        env = self.environment_builder(
            node_info=node_info,
            user_query=user_query,
            registry=registry,
            llm_resource_filter=llm_resource_filter,
            **fallback_limits,
        )
        return SpecSelectionResult(
            filtered_env=env,
            diagnostics=SelectorDiagnostics(
                path=SelectionPath.QUERY_FALLBACK,
                fallback_reason=reason,
            ),
            nl_spec=None,
        )


def _candidate_search_text(spec: NLSpec, nl: str) -> str:
    return " ".join(
        part
        for part in (
            spec.concept_id,
            spec.concept_name,
            spec.semantic_type,
            spec.region_type,
            nl,
        )
        if part
    )


def _limits_for_source_type(source_type: str, fallback_limits: dict[str, int]) -> dict[str, int]:
    zero = {
        "top_global_context": 0,
        "top_local_context": 0,
        "top_bo": 0,
        "top_function": 0,
    }
    if source_type == "context":
        zero["top_global_context"] = fallback_limits.get("top_global_context", 5)
        zero["top_local_context"] = fallback_limits.get("top_local_context", 5)
    elif source_type in {"bo_field", "naming_sql"}:
        zero["top_bo"] = fallback_limits.get("top_bo", 5)
    elif source_type == "function":
        zero["top_function"] = fallback_limits.get("top_function", 5)
    return zero


def _merge_filtered_environments(
    left: FilteredEnvironment,
    right: FilteredEnvironment,
    limits: dict[str, int],
) -> FilteredEnvironment:
    env = FilteredEnvironment(
        selected_global_contexts=_merge_resources(
            left.selected_global_contexts,
            right.selected_global_contexts,
            limits.get("top_global_context", 5),
        ),
        visible_local_context=_merge_resources(
            left.visible_local_context,
            right.visible_local_context,
            limits.get("top_local_context", 5),
        ),
        selected_bos=_merge_resources(left.selected_bos, right.selected_bos, limits.get("top_bo", 5)),
        selected_functions=_merge_resources(
            left.selected_functions,
            right.selected_functions,
            limits.get("top_function", 5),
        ),
    )
    return _with_ids(env)


def _with_ids(env: FilteredEnvironment) -> FilteredEnvironment:
    env.selected_global_context_ids = [getattr(item, "resource_id", "") for item in env.selected_global_contexts]
    env.selected_local_context_ids = [getattr(item, "resource_id", "") for item in env.visible_local_context]
    env.selected_bo_ids = [getattr(item, "resource_id", "") for item in env.selected_bos]
    env.selected_function_ids = [getattr(item, "resource_id", "") for item in env.selected_functions]
    return env


def _merge_resources(left: list, right: list, limit: int) -> list:
    selected = []
    selected_ids = set()
    for item in [*left, *right]:
        resource_id = getattr(item, "resource_id", "")
        if not resource_id or resource_id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(resource_id)
        if len(selected) >= limit:
            break
    return selected


def _has_any_selected_resource(env: FilteredEnvironment) -> bool:
    return any(
        [
            env.selected_global_contexts,
            env.visible_local_context,
            env.selected_bos,
            env.selected_functions,
        ]
    )
```

- [ ] **Step 4: Run selector tests**

Run:

```bash
python -m unittest tests.test_spec_resource_selector
```

Expected: PASS.

- [ ] **Step 5: Run existing environment tests**

Run:

```bash
python -m unittest tests.test_environment
```

Expected: PASS. This confirms the selector did not disturb the current filtering implementation.

- [ ] **Step 6: Commit Task 3**

```bash
git add agent/environment/spec_resource_selector.py tests/test_spec_resource_selector.py
git commit -m "feat: add spec-guided resource selector"
```

## Task 4: ValueLogicGenerator Integration

**Files:**
- Modify: `D:\workspace\edsl_generation\agent\value_logic_generator.py`
- Modify: `D:\workspace\edsl_generation\tests\test_value_logic_generator.py`

- [ ] **Step 1: Update fake planner in tests to accept spec**

Modify `FakePlanner.plan()` in `tests/test_value_logic_generator.py`:

```python
class FakePlanner:
    def __init__(self):
        self.calls = []

    def plan(self, *, node_info, user_query, filtered_env, nl_spec=None):
        self.calls.append(
            {
                "node_info": node_info,
                "user_query": user_query,
                "filtered_env": filtered_env,
                "nl_spec": nl_spec,
            }
        )
        return Plan.model_validate(
            {
                "nodes": [
                    {
                        "type": "return",
                        "value": {
                            "type": "select_one",
                            "bo": "BB_PREP_SUB",
                            "filter": {
                                "type": "compare",
                                "op": "==",
                                "left": {"type": "context_path", "path": "it.ID"},
                                "right": {"type": "context_path", "path": "$ctx$.id"},
                            },
                        },
                    }
                ]
            }
        )
```

- [ ] **Step 2: Write failing integration tests**

Append to `ValueLogicGeneratorTest` in `tests/test_value_logic_generator.py`:

```python
    def test_spec_selector_result_is_sent_to_planner(self):
        from agent.environment.environment import FilteredEnvironment
        from agent.environment.spec_resource_selector import SpecSelectionResult
        from agent.nl_spec.models import NLSpec, SelectorDiagnostics, SelectionPath, ValueSourceCandidate

        class FakeSpecSelector:
            def __init__(self):
                self.calls = []
                self.spec = NLSpec(
                    concept_id="cbs.account.balance",
                    concept_name="账户余额",
                    semantic_type="amount",
                    region_type="basic_info",
                    value_source_candidates=[
                        ValueSourceCandidate(source_type="bo_field", nl="从账户余额相关 BO 查询余额字段。")
                    ],
                    evidence=["term:账户余额"],
                )

            def select(self, **kwargs):
                self.calls.append(kwargs)
                return SpecSelectionResult(
                    filtered_env=FilteredEnvironment(),
                    diagnostics=SelectorDiagnostics(
                        path=SelectionPath.SPEC_GUIDED,
                        concept_id="cbs.account.balance",
                        concept_name="账户余额",
                    ),
                    nl_spec=self.spec,
                )

        planner = FakePlanner()
        selector = FakeSpecSelector()
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            spec_resource_selector=selector,
            llm_planner=planner,
        )

        generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1]",
                node={"node_id": "node-1", "tree_node_type": "simple_leaf", "name": "BALANCE"},
                query="取账户余额",
                region_type="basic_info",
                cbs_name="账户余额",
                edsl_tree=sample_edsl_tree_payload(),
            )
        )

        self.assertEqual(selector.calls[0]["region_type"], "basic_info")
        self.assertEqual(selector.calls[0]["cbs_name"], "账户余额")
        self.assertEqual(planner.calls[0]["nl_spec"].concept_id, "cbs.account.balance")

    def test_old_request_shape_uses_selector_fallback_without_spec_summary(self):
        planner = FakePlanner()
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter(
                {
                    "bo": [{"resource_id": "bo.0000"}],
                    "function": [],
                    "local_context": [],
                    "global_context": [],
                }
            ),
            llm_planner=planner,
        )

        generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1]",
                node={"node_id": "node-1", "tree_node_type": "simple_leaf", "name": "SUB_INFO"},
                query="query one prep sub by id",
                edsl_tree=sample_edsl_tree_payload(),
            )
        )

        self.assertIsNone(planner.calls[0]["nl_spec"])
```

- [ ] **Step 3: Run integration tests to verify they fail**

Run:

```bash
python -m unittest tests.test_value_logic_generator
```

Expected: FAIL with `ValueLogicGenerator.__init__()` not accepting `spec_resource_selector` or `FakePlanner.plan()` argument mismatch in old implementation.

- [ ] **Step 4: Inject selector in ValueLogicGenerator**

Modify imports in `agent/value_logic_generator.py`:

```python
from agent.environment.spec_resource_selector import SpecResourceSelector
from agent.nl_spec.generator import NLSpecGenerator
```

Modify `ValueLogicGenerator.__init__()`:

```python
    def __init__(
        self,
        *,
        resource_loader: ResourceLoader | None = None,
        llm_resource_filter: Any | None = None,
        llm_difficulty_router: Any | None = None,
        llm_planner: LLMPlanner | None = None,
        nl_spec_generator: NLSpecGenerator | None = None,
        spec_resource_selector: Any | None = None,
    ):
        self.resource_loader = resource_loader or default_resource_loader
        self.llm_resource_filter = llm_resource_filter or LLMResourceFilter()
        self.llm_difficulty_router = llm_difficulty_router or LLMDifficultyRouter()
        self.llm_planner = llm_planner or LLMPlanner()
        self.nl_spec_generator = nl_spec_generator or NLSpecGenerator()
        self.spec_resource_selector = spec_resource_selector or SpecResourceSelector(
            spec_generator=self.nl_spec_generator
        )
```

- [ ] **Step 5: Replace direct environment build with selector**

Modify `_generate_expression_by_plan()` in `agent/value_logic_generator.py`:

```python
    def _generate_expression_by_plan(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        node_info = self._to_node_def(request.node, request.node_path)
        route = self._route_resources(node_info, request.query)
        resource_limits = _resource_limits_from_route(route)
        selection = self.spec_resource_selector.select(
            node_info=node_info,
            user_query=request.query,
            site_id=request.site_id,
            project_id=request.project_id,
            region_type=request.region_type,
            cbs_name=request.cbs_name,
            registry=ctx.resources.loaded,
            fallback_limits=resource_limits,
            llm_resource_filter=self.llm_resource_filter,
        )
        plan = self.llm_planner.plan(
            node_info=node_info,
            user_query=request.query,
            filtered_env=selection.filtered_env,
            nl_spec=selection.nl_spec,
        )
        ast = build_ast(plan)
        validate_ast(ast)
        expression = generate_expression(ast)

        return ValueLogicResult(
            node_id=self._node_id(request.node),
            logic_type="expression",
            expression=expression,
            source=ValueLogicSource(source_type="plan")
        )
```

- [ ] **Step 6: Run value logic tests**

Run:

```bash
python -m unittest tests.test_value_logic_generator
```

Expected: PASS.

- [ ] **Step 7: Run selector and generator tests together**

Run:

```bash
python -m unittest tests.test_nl_spec_models tests.test_nl_spec_generator tests.test_spec_resource_selector tests.test_value_logic_generator
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add agent/value_logic_generator.py tests/test_value_logic_generator.py
git commit -m "feat: route value generation through spec selector"
```

## Task 5: Planner Spec Summary And Prompt Boundary

**Files:**
- Modify: `D:\workspace\edsl_generation\agent\planner\llm_planner.py`
- Modify: `D:\workspace\edsl_generation\prompt.json`
- Modify: `D:\workspace\edsl_generation\tests\test_llm_planner.py`
- Modify: `D:\workspace\edsl_generation\tests\test_planner_prompt.py`

- [ ] **Step 1: Write failing LLMPlanner spec-summary tests**

Add imports to `tests/test_llm_planner.py`:

```python
from agent.nl_spec.models import NLSpec, ValueSourceCandidate
```

Modify test prompts in `setUp()` to include `{{nl_spec_json}}`:

```python
            "planner": {
                "zh": (
                    "planner {{user_requirement}} {{node_info_json}} "
                    "{{resources_json}} {{nl_spec_json}} {{plan_schema_json}}"
                )
            },
            "planner_repair": {
                "zh": (
                    "repair {{user_requirement}} {{node_info_json}} "
                    "{{resources_json}} {{nl_spec_json}} {{plan_schema_json}} "
                    "{{invalid_plan_json}} {{error_message}}"
                )
            },
```

Append these tests to `LLMPlannerTest`:

```python
    def test_plan_includes_nl_spec_summary_when_present(self):
        client = FakeClient(
            [
                '{"nodes":[{"type":"return","value":{"type":"context_path","path":"$ctx$.balance"}}]}',
            ]
        )
        spec = NLSpec(
            concept_id="cbs.account.balance",
            concept_name="账户余额",
            semantic_type="amount",
            region_type="basic_info",
            value_source_candidates=[
                ValueSourceCandidate(source_type="context", nl="优先从上下文获取账户余额。")
            ],
            evidence=["term:账户余额"],
        )

        LLMPlanner(client=client).plan(
            node_info=_node_info(),
            user_query="取账户余额",
            filtered_env=FilteredEnvironment(),
            nl_spec=spec,
        )

        self.assertIn('"concept_id":"cbs.account.balance"', client.calls[0]["prompt"])
        self.assertIn("优先从上下文获取账户余额", client.calls[0]["prompt"])

    def test_repair_includes_nl_spec_summary_when_present(self):
        client = FakeClient(
            [
                '{"nodes":[]}',
                '{"nodes":[{"type":"return","value":{"type":"literal","value":null}}]}',
            ]
        )
        spec = NLSpec(
            concept_id="cbs.account.balance",
            concept_name="账户余额",
            semantic_type="amount",
            region_type="basic_info",
            value_source_candidates=[
                ValueSourceCandidate(source_type="context", nl="优先从上下文获取账户余额。")
            ],
            evidence=["term:账户余额"],
        )

        LLMPlanner(client=client).plan(
            node_info=_node_info(),
            user_query="取账户余额",
            filtered_env=FilteredEnvironment(),
            nl_spec=spec,
        )

        self.assertIn('"concept_id":"cbs.account.balance"', client.calls[1]["prompt"])
```

- [ ] **Step 2: Write failing planner prompt boundary test**

Append to `tests/test_planner_prompt.py`:

```python
    def test_planner_prompt_requires_spec_but_forbids_unselected_resources(self):
        prompt = prompt_manager.render(
            "planner",
            lang="zh",
            user_requirement="取账户余额",
            node_info_json="{}",
            resources_json='{"bo":[],"function":[],"global_context":[],"local_context":[]}',
            nl_spec_json='{"concept_name":"账户余额"}',
            plan_schema_json="{}",
        )

        self.assertIn("NL Spec", prompt)
        self.assertIn("只能使用 resources", prompt)
        self.assertIn("禁止编造", prompt)
        self.assertIn("未出现在 resources", prompt)
```

If `tests/test_planner_prompt.py` currently imports `prompt_manager`, keep the existing import. If it imports only helper functions, add:

```python
from agent.llm.prompt_manager import prompt_manager
```

- [ ] **Step 3: Run planner tests to verify they fail**

Run:

```bash
python -m unittest tests.test_llm_planner tests.test_planner_prompt
```

Expected: FAIL with `plan()` not accepting `nl_spec` and prompt missing `nl_spec_json` boundary wording.

- [ ] **Step 4: Extend LLMPlanner signature and prompt variables**

Modify `agent/planner/llm_planner.py`:

```python
    def plan(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        filtered_env: FilteredEnvironment,
        nl_spec: Any | None = None,
    ) -> Plan:
        if not self.is_usable:
            raise RuntimeError("LLM planner is not usable")

        resources_json = _dump_json(_summarize_filtered_environment(filtered_env))
        node_info_json = _dump_json(_summarize_node(node_info))
        nl_spec_json = _dump_json(_summarize_nl_spec(nl_spec))
        plan_schema_json = _dump_json(PLAN_SCHEMA)
```

In the `generate_by_llm()` call inside `plan()`, add:

```python
                nl_spec_json=nl_spec_json,
```

In the `_repair()` call from `plan()`, add:

```python
                nl_spec_json=nl_spec_json,
```

Modify `_repair()` signature:

```python
    def _repair(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        resources_json: str,
        node_info_json: str,
        nl_spec_json: str,
        plan_schema_json: str,
        invalid_plan_json: str,
        error_message: str,
    ) -> Plan:
```

In repair `generate_by_llm()`, add:

```python
            nl_spec_json=nl_spec_json,
```

Add helper near `_summarize_filtered_environment()`:

```python
def _summarize_nl_spec(nl_spec: Any | None) -> dict[str, Any]:
    if nl_spec is None:
        return {}
    if hasattr(nl_spec, "to_planner_summary"):
        summary = nl_spec.to_planner_summary()
        if isinstance(summary, dict):
            return summary
    if isinstance(nl_spec, dict):
        return nl_spec
    return {}
```

- [ ] **Step 5: Update planner prompts**

Modify `prompt.json` `planner.zh` text to include this block before `resources:`:

```text
nl_spec:
{{nl_spec_json}}

NL Spec rules:
12. If nl_spec is not empty, use it as the business semantic constraint for choosing the value path.
13. NL Spec explains preferred value sources, but it is not a resource list.
14. You can only use resources listed in resources. 禁止编造未出现在 resources 中的 BO、context、function 或 naming SQL.
15. If nl_spec mentions a concept whose resource is not present in resources, do not reference that missing resource in the plan.
```

Modify `prompt.json` `planner_repair.zh` text to include:

```text
nl_spec:
{{nl_spec_json}}

Repair rules:
- Keep the NL Spec business constraint when nl_spec is not empty.
- You can only use resources listed in resources. 禁止编造未出现在 resources 中的 BO、context、function 或 naming SQL.
```

- [ ] **Step 6: Run planner tests**

Run:

```bash
python -m unittest tests.test_llm_planner tests.test_planner_prompt
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add agent/planner/llm_planner.py prompt.json tests/test_llm_planner.py tests/test_planner_prompt.py
git commit -m "feat: pass nl spec summary to planner"
```

## Task 6: End-To-End Regression And Cleanup

**Files:**
- Modify only files touched by previous tasks if tests expose small defects.
- No new production files expected.

- [ ] **Step 1: Run focused new tests**

Run:

```bash
python -m unittest tests.test_nl_spec_models tests.test_nl_spec_generator tests.test_spec_resource_selector
```

Expected: PASS.

- [ ] **Step 2: Run integration tests**

Run:

```bash
python -m unittest tests.test_value_logic_generator tests.test_llm_planner tests.test_planner_prompt
```

Expected: PASS.

- [ ] **Step 3: Run existing resource filtering regression tests**

Run:

```bash
python -m unittest tests.test_environment tests.test_difficulty_router
```

Expected: PASS. These tests protect the fallback resource filtering path.

- [ ] **Step 4: Run the broader related suite**

Run:

```bash
python -m unittest tests.test_resource_search_tool tests.test_resource_loader tests.test_edsl_gen_entry tests.test_edsl_gen_entry_integration
```

Expected: PASS.

- [ ] **Step 5: Check OpenSpec status**

Run:

```bash
openspec status --change "add-nl-spec-guided-resource-selection"
```

Expected output includes:

```text
All artifacts complete!
```

- [ ] **Step 6: Inspect git diff**

Run:

```bash
git diff -- agent tests prompt.json
```

Expected: diff only contains NL Spec models/providers/generator, selector, generator integration, planner prompt changes, and tests.

- [ ] **Step 7: Commit final verification notes if any test-only corrections were made**

If Step 1 through Step 6 required additional code or test edits, commit those edits:

```bash
git add agent tests prompt.json
git commit -m "test: cover nl spec guided selection flow"
```

If no files changed after Task 5, skip this commit.

## Self-Review

- Spec coverage: Task 1 covers optional `region_type` and `cbs_name` inputs plus NL Spec output format. Task 2 covers mock term and region experience resources and generation. Task 3 covers `SpecResourceSelector`, `source_type + nl` constraints, spec-first priority, fallback reasons, and diagnostics. Task 4 covers the generation chain integration. Task 5 covers planner spec usage and hard resource boundaries. Task 6 covers verification.
- Placeholder scan: This plan intentionally avoids unspecified provider behavior by using concrete mock providers, concrete model fields, concrete commands, and concrete expected outcomes.
- Type consistency: `NLSpec`, `ValueSourceCandidate`, `SelectorDiagnostics`, `SelectionPath`, `SpecSelectionResult`, `NLSpecGenerator.generate()`, and `SpecResourceSelector.select()` signatures are defined before later tasks use them.
