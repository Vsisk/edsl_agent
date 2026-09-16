from __future__ import annotations

from agent.workflow.context import ContextPolicy
from agent.workflow.core import WorkflowDefinition
from agent.workflow.executor import WorkflowRuntime
from agent.workflow.transition import RetryPolicy, TransitionPolicy, TransitionRule
from agent.workflows.value_logic.child_workflows import (
    create_bo_field_workflow_factory,
    create_expression_workflow_factory,
    create_sql_workflow_factory,
)
from agent.workflows.value_logic.stages import (
    FinalizeInput,
    FinalizeValueLogicResultStage,
    HandleBranchOutcomeStage,
    HandleOutcomeInput,
    InvokeBranchInput,
    InvokeBranchStage,
    PrepareInput,
    PrepareValueLogicStage,
    RouteInput,
    RouteValueLogicStage,
)


class ValueLogicWorkflowFactory:
    def __init__(
        self,
        *,
        prepare_context_fn,
        resolve_sql_fn,
        resolve_bo_field_fn,
        summary_fn,
        expression_fn,
        child_runtime: WorkflowRuntime | None = None,
    ) -> None:
        self.prepare_context_fn = prepare_context_fn
        self.resolve_sql_fn = resolve_sql_fn
        self.resolve_bo_field_fn = resolve_bo_field_fn
        self.summary_fn = summary_fn
        self.expression_fn = expression_fn
        self.child_runtime = child_runtime or WorkflowRuntime()

    def create_definition(self) -> WorkflowDefinition:
        prepare = PrepareValueLogicStage(self.prepare_context_fn)
        route = RouteValueLogicStage()
        invoke_branch = InvokeBranchStage(
            runtime=self.child_runtime,
            sql_workflow_factory=create_sql_workflow_factory(self.resolve_sql_fn),
            bo_field_workflow_factory=create_bo_field_workflow_factory(self.resolve_bo_field_fn),
            expression_workflow_factory=create_expression_workflow_factory(self.expression_fn),
            summary_fn=self.summary_fn,
        )
        handle_outcome = HandleBranchOutcomeStage()
        finalize = FinalizeValueLogicResultStage()

        _bind_stage_metadata(
            prepare,
            input_model=PrepareInput,
            harness_bindings={"request": "request"},
        )
        _bind_stage_metadata(
            route,
            input_model=RouteInput,
            artifact_bindings={"target": "target"},
        )
        _bind_stage_metadata(
            invoke_branch,
            input_model=InvokeBranchInput,
            workflow_input_bindings={"parent_state": "parent_state"},
            artifact_bindings={
                "generation_context": "generation_context",
                "active_branch": "active_branch",
            },
            harness_bindings={
                "request": "request",
                "environment": "environment",
            },
        )
        _bind_stage_metadata(
            handle_outcome,
            input_model=HandleOutcomeInput,
            artifact_bindings={
                "branch_outcome": "branch_outcome",
                "branch_history": "branch_history",
            },
        )
        _bind_stage_metadata(
            finalize,
            input_model=FinalizeInput,
            artifact_bindings={"value_logic_result": "value_logic_result"},
        )

        return WorkflowDefinition(
            name="value_logic_generation",
            entry_stage="prepare",
            stages={
                "prepare": prepare,
                "route": route,
                "invoke_branch": invoke_branch,
                "handle_outcome": handle_outcome,
                "finalize": finalize,
            },
            default_transitions={
                "prepare": "route",
                "route": "invoke_branch",
                "invoke_branch": "handle_outcome",
                "handle_outcome": "finalize",
                "finalize": None,
            },
            terminal_stages={"finalize"},
            transition_policy=TransitionPolicy(
                rules=(
                    TransitionRule(
                        from_stage="handle_outcome",
                        to_stage="invoke_branch",
                        result_status="succeeded",
                        output_equals={"active_branch": "expression"},
                    ),
                    TransitionRule(
                        from_stage="handle_outcome",
                        to_stage="invoke_branch",
                        result_status="succeeded",
                        output_equals={"active_branch": "sql"},
                    ),
                    TransitionRule(
                        from_stage="handle_outcome",
                        to_stage="invoke_branch",
                        result_status="succeeded",
                        output_equals={"active_branch": "bo_field"},
                    ),
                )
            ),
            retry_policy=RetryPolicy(
                max_total_transitions=16,
                max_retry_per_stage=4,
                max_same_artifact_fingerprint=8,
                artifact_keys=("active_branch", "branch_history"),
            ),
        )


def _bind_stage_metadata(
    stage,
    *,
    input_model,
    workflow_input_bindings: dict[str, str] | None = None,
    artifact_bindings: dict[str, str] | None = None,
    harness_bindings: dict[str, str] | None = None,
) -> None:
    stage.input_model = input_model
    stage.artifact_bindings = artifact_bindings or {}
    stage.optional_artifact_bindings = {}
    stage.environment_bindings = harness_bindings or {}
    stage.context_policy = ContextPolicy(
        input_model=input_model,
        workflow_input_bindings=workflow_input_bindings or {},
        artifact_bindings=stage.artifact_bindings,
        harness_bindings=stage.environment_bindings,
    )
