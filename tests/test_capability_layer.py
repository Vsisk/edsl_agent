from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent.expression_workflow import (
    CapabilityRegistries,
    ContextAssembler,
    ContextPolicy,
    HarnessContext,
    KnowledgeDefinition,
    SkillDefinition,
    ToolDefinition,
    WorkflowDefinition,
)
from agent.expression_workflow.core import Stage, StageResult, WorkflowRunState
from agent.expression_workflow.expression_capabilities import (
    create_expression_capability_registries,
)


@dataclass
class CapabilityInput:
    query: str
    tools: dict
    skills: list
    knowledge: list


class CapabilityStage(Stage):
    name = "resource_search"
    input_model = CapabilityInput
    context_policy = ContextPolicy(
        input_model=CapabilityInput,
        workflow_input_bindings={"query": "query"},
        tool_names=("search_context", "inspect_return_type"),
        skill_names=("resource_search",),
        knowledge_tags=("resource",),
        knowledge_scope="expression",
        inject_capabilities=True,
    )

    def execute(self, stage_input: CapabilityInput) -> StageResult:
        return StageResult(
            success=True,
            outputs={
                "tool_names": sorted(stage_input.tools),
                "skill_names": [skill.name for skill in stage_input.skills],
                "knowledge_ids": [
                    document.definition.knowledge_id for document in stage_input.knowledge
                ],
            },
        )


def test_tool_registry_wraps_callable_and_rejects_duplicates() -> None:
    registries = CapabilityRegistries()
    tool = ToolDefinition(
        name="inspect_return_type",
        description="Inspect return type",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        concurrency_safe=True,
        execute=lambda value: {"normalized": value},
    )

    registries.tools.register(tool)

    assert registries.tools.get("inspect_return_type").execute("String") == {
        "normalized": "String"
    }
    with pytest.raises(ValueError, match="tool already registered"):
        registries.tools.register(tool)


def test_skill_registry_filters_by_workflow_and_stage() -> None:
    registries = CapabilityRegistries()
    registries.skills.register(
        SkillDefinition(
            name="resource_search",
            description="Search resources",
            instruction="Select resources.",
            applicable_workflows=("expression_generation",),
            applicable_stages=("resource_search",),
            allowed_tools=("search_context",),
            knowledge_requirements=("expression.context",),
        )
    )
    registries.skills.register(
        SkillDefinition(
            name="other",
            description="Other",
            instruction="Other.",
            applicable_workflows=("other_workflow",),
            applicable_stages=("resource_search",),
        )
    )

    selected = registries.skills.select(
        workflow="expression_generation",
        stage="resource_search",
    )

    assert [skill.name for skill in selected] == ["resource_search"]


def test_knowledge_registry_search_loads_markdown_and_dedupes(tmp_path) -> None:
    path = tmp_path / "context.md"
    path.write_text("# Context\n\nUse selected context only.", encoding="utf-8")
    registries = CapabilityRegistries()
    definition = KnowledgeDefinition(
        knowledge_id="expression.context",
        title="Context",
        scope="expression",
        workflow="expression_generation",
        stage="resource_search",
        tags=("resource", "context"),
        priority=10,
        source_path=path,
    )
    registries.knowledge.register(definition)

    documents = registries.knowledge.load(
        knowledge_ids=("expression.context", "expression.context"),
        workflow="expression_generation",
        stage="resource_search",
        scope="expression",
        tags=("resource",),
    )

    assert len(documents) == 1
    assert documents[0].definition.knowledge_id == "expression.context"
    assert "Use selected context only." in documents[0].content


def test_context_assembler_attaches_declared_capabilities_only() -> None:
    registries = create_expression_capability_registries(
        tool_callables={
            "search_context": lambda **kwargs: {"contexts": []},
            "inspect_return_type": lambda **kwargs: {"type": "String"},
        }
    )
    stage = CapabilityStage()
    definition = WorkflowDefinition(
        name="expression_generation",
        entry_stage="resource_search",
        stages={"resource_search": stage},
        default_transitions={"resource_search": None},
        terminal_stages={"resource_search"},
    )
    state = WorkflowRunState(
        workflow_name="expression_generation",
        workflow_input={"query": "find amount"},
    )

    stage_context = ContextAssembler().build(
        harness_context=HarnessContext(capability_registries=registries),
        workflow_definition=definition,
        workflow_state=state,
        stage=stage,
    )
    stage_input = stage_context.to_stage_input()

    assert sorted(stage_input.tools) == ["inspect_return_type", "search_context"]
    assert [skill.name for skill in stage_input.skills] == ["resource_search"]
    assert "search_bo" not in stage_input.tools
    assert {
        document.definition.knowledge_id for document in stage_input.knowledge
    } >= {
        "expression.resource-model",
        "expression.context",
        "expression.bo",
        "expression.naming-sql",
        "expression.return-type",
    }
    assert all(document.content.strip() for document in stage_input.knowledge)


def test_expression_default_capabilities_cover_required_stage_names() -> None:
    registries = create_expression_capability_registries()

    assert {
        "search_context",
        "search_bo",
        "search_namingsql",
        "inspect_return_type",
        "validate_ast",
        "search_reference_node",
    } == {tool.name for tool in registries.tools.list()}
    assert {
        "resource_search",
        "expression_generation",
        "expression_repair",
    } == {skill.name for skill in registries.skills.list()}
    assert {
        "expression.resource-model",
        "expression.context",
        "expression.bo",
        "expression.naming-sql",
        "expression.return-type",
        "expression.ast",
    } == {knowledge.knowledge_id for knowledge in registries.knowledge.list()}
