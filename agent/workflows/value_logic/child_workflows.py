from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.workflow.context import ContextPolicy
from agent.workflow.core import Observation, ObservationSeverity, Stage, StageResult, WorkflowDefinition
from agent.workflows.value_logic.outcome import ValueLogicBranchOutcome


@dataclass
class BranchWorkflowInput:
    request: Any
    generation_context: Any


class SqlWorkflowStage(Stage):
    name = "resolve_sql"
    input_model = BranchWorkflowInput

    def __init__(self, resolve_sql_fn: Callable[[Any, Any], Any | None]) -> None:
        self.resolve_sql_fn = resolve_sql_fn

    def execute(self, stage_input: BranchWorkflowInput) -> StageResult:
        result = self.resolve_sql_fn(stage_input.request, stage_input.generation_context)
        if isinstance(result, ValueLogicBranchOutcome):
            outcome = result
        elif result is None:
            outcome = ValueLogicBranchOutcome(
                status="fallback",
                branch_type="sql",
                fallback_target="expression",
                handoff_artifacts=_sql_handoff_artifacts(stage_input.generation_context),
            )
        else:
            outcome = ValueLogicBranchOutcome(
                status="success",
                branch_type="sql",
                result=result,
            )
        return StageResult(outputs={"branch_outcome": outcome})


class BoFieldWorkflowStage(Stage):
    name = "resolve_bo_field"
    input_model = BranchWorkflowInput

    def __init__(self, resolve_bo_field_fn: Callable[[Any, Any], Any | None]) -> None:
        self.resolve_bo_field_fn = resolve_bo_field_fn

    def execute(self, stage_input: BranchWorkflowInput) -> StageResult:
        result = self.resolve_bo_field_fn(stage_input.request, stage_input.generation_context)
        if isinstance(result, ValueLogicBranchOutcome):
            outcome = result
        elif result is None:
            outcome = ValueLogicBranchOutcome(
                status="fallback",
                branch_type="bo_field",
                fallback_target="expression",
                handoff_artifacts={},
            )
        else:
            outcome = ValueLogicBranchOutcome(
                status="success",
                branch_type="bo_field",
                result=result,
            )
        return StageResult(outputs={"branch_outcome": outcome})


class ExpressionWorkflowStage(Stage):
    name = "run_expression"
    input_model = BranchWorkflowInput

    def __init__(self, expression_fn: Callable[[Any, Any], Any]) -> None:
        self.expression_fn = expression_fn

    def execute(self, stage_input: BranchWorkflowInput) -> StageResult:
        try:
            result = self.expression_fn(stage_input.request, stage_input.generation_context)
        except Exception as exc:
            outcome = ValueLogicBranchOutcome(
                status="failed",
                branch_type="expression",
                observation=Observation(
                    code="INTERNAL_ERROR",
                    source_stage=self.name,
                    message=str(exc),
                    retryable=False,
                    severity=ObservationSeverity.ERROR,
                ),
            )
            return StageResult(outputs={"branch_outcome": outcome})
        if isinstance(result, ValueLogicBranchOutcome):
            outcome = result
        else:
            outcome = ValueLogicBranchOutcome(
                status="success",
                branch_type="expression",
                result=result,
            )
        return StageResult(outputs={"branch_outcome": outcome})


class SingleStageBranchWorkflowFactory:
    def __init__(self, *, name: str, stage: Stage) -> None:
        self.name = name
        self.stage = stage
        _bind_branch_stage(self.stage)

    def create_definition(self) -> WorkflowDefinition:
        return WorkflowDefinition(
            name=self.name,
            entry_stage=self.stage.name,
            stages={self.stage.name: self.stage},
            default_transitions={self.stage.name: None},
            terminal_stages={self.stage.name},
        )


def create_sql_workflow_factory(resolve_sql_fn: Callable[[Any, Any], Any | None]) -> SingleStageBranchWorkflowFactory:
    return SingleStageBranchWorkflowFactory(
        name="sql_value_logic_generation",
        stage=SqlWorkflowStage(resolve_sql_fn),
    )


def create_bo_field_workflow_factory(
    resolve_bo_field_fn: Callable[[Any, Any], Any | None],
) -> SingleStageBranchWorkflowFactory:
    return SingleStageBranchWorkflowFactory(
        name="bo_field_value_logic_generation",
        stage=BoFieldWorkflowStage(resolve_bo_field_fn),
    )


def create_expression_workflow_factory(expression_fn: Callable[[Any, Any], Any]) -> SingleStageBranchWorkflowFactory:
    return SingleStageBranchWorkflowFactory(
        name="expression_generation",
        stage=ExpressionWorkflowStage(expression_fn),
    )


def _bind_branch_stage(stage: Stage) -> None:
    stage.input_model = BranchWorkflowInput
    stage.artifact_bindings = {"generation_context": "generation_context"}
    stage.environment_bindings = {"request": "request"}
    stage.context_policy = ContextPolicy(
        input_model=BranchWorkflowInput,
        artifact_bindings=stage.artifact_bindings,
        harness_bindings=stage.environment_bindings,
    )


def _sql_handoff_artifacts(generation_context: Any) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    filtered_env = getattr(generation_context, "filtered_env", None)
    if filtered_env is not None:
        artifacts["initial_filtered_env"] = filtered_env
    context_pack = getattr(generation_context, "context_pack", None)
    naming_sql_hint = _read_naming_sql_hint(context_pack)
    if naming_sql_hint is not None:
        artifacts["naming_sql_hint"] = naming_sql_hint
    return artifacts


def _read_naming_sql_hint(context_pack: Any) -> Any | None:
    if context_pack is None:
        return None
    if isinstance(context_pack, dict):
        return context_pack.get("naming_sql_hint")
    metadata = getattr(context_pack, "metadata", None)
    if isinstance(metadata, dict) and metadata.get("naming_sql_hint") is not None:
        return metadata["naming_sql_hint"]
    return getattr(context_pack, "naming_sql_hint", None)
