from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent.workflow import (
    ContextAssembler,
    ContextPolicy,
    HarnessContext,
    WorkflowDefinition,
    WorkflowRuntime,
)
from agent.workflow.core import Stage, StageResult, WorkflowRunState


@dataclass
class SpecInput:
    query: str
    target_node: dict


@dataclass
class ResourceInput:
    query: str
    spec: str
    resource_environment: dict
    previous_resource_observation: str | None = None


@dataclass
class GenerateInput:
    spec: str
    selected_resources: dict
    available_type_information: dict
    available_method_information: dict


@dataclass
class ValidateInput:
    expression: str
    selected_resource_metadata: dict
    type_registry: dict


class CaptureStage(Stage):
    name = "capture"
    input_model = SpecInput
    context_policy = ContextPolicy(
        input_model=SpecInput,
        workflow_input_bindings={
            "query": "query",
            "target_node": "target_node",
        },
    )

    def __init__(self) -> None:
        self.received = None

    def execute(self, stage_input: SpecInput) -> StageResult:
        self.received = stage_input
        return StageResult(success=True, outputs={"seen_query": stage_input.query})


def test_context_assembler_projects_only_declared_stage_values() -> None:
    stage = CaptureStage()
    definition = WorkflowDefinition(
        name="projection",
        entry_stage="capture",
        stages={"capture": stage},
        default_transitions={"capture": None},
        terminal_stages={"capture"},
    )
    state = WorkflowRunState(
        workflow_name="projection",
        workflow_input={
            "query": "calculate total",
            "target_node": {"field": "total"},
            "extra": "must not leak",
        },
    )
    harness = HarnessContext(
        site_id="site-1",
        project_id="project-1",
        facts={"global_secret": "must not leak"},
    )

    stage_context = ContextAssembler().build(
        harness_context=harness,
        workflow_definition=definition,
        workflow_state=state,
        stage=stage,
    )

    assert stage_context.values == {
        "query": "calculate total",
        "target_node": {"field": "total"},
    }
    assert stage_context.workflow_context.workflow_input["extra"] == "must not leak"
    assert stage_context.workflow_context.harness_context.site_id == "site-1"


def test_runtime_executes_stage_with_context_assembler_projection() -> None:
    stage = CaptureStage()
    definition = WorkflowDefinition(
        name="runtime_projection",
        entry_stage="capture",
        stages={"capture": stage},
        default_transitions={"capture": None},
        terminal_stages={"capture"},
    )
    state = WorkflowRunState(
        workflow_name="runtime_projection",
        workflow_input={
            "query": "map field",
            "target_node": {"field": "name"},
        },
    )

    result_state = WorkflowRuntime().run(
        definition=definition,
        state=state,
        environment=HarnessContext(),
    )

    assert stage.received == SpecInput(query="map field", target_node={"field": "name"})
    assert result_state.artifacts["seen_query"] == "map field"
    assert result_state.completed_stages == ["capture"]


def test_context_assembler_fails_when_required_dependency_is_missing() -> None:
    stage = CaptureStage()
    state = WorkflowRunState(
        workflow_name="missing_dependency",
        workflow_input={"query": "calculate total"},
    )

    with pytest.raises(KeyError, match="target_node"):
        ContextAssembler().build(
            harness_context=HarnessContext(),
            workflow_definition=WorkflowDefinition(
                name="missing_dependency",
                entry_stage="capture",
                stages={"capture": stage},
                default_transitions={"capture": None},
            ),
            workflow_state=state,
            stage=stage,
        )


def test_expression_stage_policy_shapes_are_supported() -> None:
    resource_stage = type(
        "ResourceStage",
        (Stage,),
        {
            "name": "resource_search",
            "input_model": ResourceInput,
            "context_policy": ContextPolicy(
                input_model=ResourceInput,
                workflow_input_bindings={"query": "query"},
                artifact_bindings={"spec": "spec"},
                harness_bindings={"resource_environment": "resource_environment"},
                optional_harness_bindings={
                    "previous_resource_observation": "previous_resource_observation"
                },
            ),
            "execute": lambda self, stage_input: StageResult(success=True),
        },
    )()
    generate_stage = type(
        "GenerateStage",
        (Stage,),
        {
            "name": "generate",
            "input_model": GenerateInput,
            "context_policy": ContextPolicy(
                input_model=GenerateInput,
                artifact_bindings={
                    "spec": "spec",
                    "selected_resources": "selected_resources",
                },
                harness_bindings={
                    "available_type_information": "available_type_information",
                    "available_method_information": "available_method_information",
                },
            ),
            "execute": lambda self, stage_input: StageResult(success=True),
        },
    )()
    validate_stage = type(
        "ValidateStage",
        (Stage,),
        {
            "name": "validate",
            "input_model": ValidateInput,
            "context_policy": ContextPolicy(
                input_model=ValidateInput,
                artifact_bindings={
                    "expression": "expression",
                    "selected_resource_metadata": "selected_resource_metadata",
                },
                harness_bindings={"type_registry": "type_registry"},
            ),
            "execute": lambda self, stage_input: StageResult(success=True),
        },
    )()
    state = WorkflowRunState(
        workflow_name="expression_policy_shapes",
        workflow_input={"query": "q"},
        artifacts={
            "spec": "s",
            "selected_resources": {"bo": ["Order"]},
            "expression": "order.amount",
            "selected_resource_metadata": {"Order": ["amount"]},
        },
    )
    harness = HarnessContext(
        facts={
            "resource_environment": {"latest": True},
            "available_type_information": {"Order": "bo"},
            "available_method_information": {"sum": "method"},
            "type_registry": {"Order": "bo"},
        }
    )
    assembler = ContextAssembler()

    resource_context = assembler.build(
        harness, WorkflowDefinition("wf", "resource_search", {}, {}), state, resource_stage
    )
    generate_context = assembler.build(
        harness, WorkflowDefinition("wf", "generate", {}, {}), state, generate_stage
    )
    validate_context = assembler.build(
        harness, WorkflowDefinition("wf", "validate", {}, {}), state, validate_stage
    )

    assert resource_context.to_stage_input() == ResourceInput(
        query="q",
        spec="s",
        resource_environment={"latest": True},
    )
    assert generate_context.to_stage_input() == GenerateInput(
        spec="s",
        selected_resources={"bo": ["Order"]},
        available_type_information={"Order": "bo"},
        available_method_information={"sum": "method"},
    )
    assert validate_context.to_stage_input() == ValidateInput(
        expression="order.amount",
        selected_resource_metadata={"Order": ["amount"]},
        type_registry={"Order": "bo"},
    )
