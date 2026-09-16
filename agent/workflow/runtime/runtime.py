from __future__ import annotations

from typing import Any

from agent.workflow.context import ContextAssembler
from agent.workflow.runtime.definition import WorkflowDefinition
from agent.workflow.runtime.run_state import WorkflowRunState, WorkflowStatus
from agent.workflow.runtime.stage import StageExecutionError, execute_stage
from agent.workflow.runtime.stage_result import StageResult
from agent.workflow.runtime.subworkflow import SubWorkflowResult
from agent.workflow.transition import LoopGuard, RetryPolicy, TransitionPolicy


class WorkflowRuntime:
    def __init__(
        self,
        *,
        context_assembler: ContextAssembler | None = None,
        transition_policy: TransitionPolicy | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.context_assembler = context_assembler or ContextAssembler()
        self.transition_policy = transition_policy or TransitionPolicy()
        self.retry_policy = retry_policy or RetryPolicy()

    def run(
        self,
        *,
        definition: WorkflowDefinition,
        state: WorkflowRunState,
        environment: Any,
    ) -> WorkflowRunState:
        current_stage = definition.entry_stage

        while current_stage is not None:
            try:
                result = self.run_stage(
                    definition=definition,
                    stage_name=current_stage,
                    state=state,
                    environment=environment,
                )
            except StageExecutionError as exc:
                state.status = WorkflowStatus.FAILED
                state.record_stage_failure(current_stage, exc.error)
                raise
            except Exception as exc:
                state.status = WorkflowStatus.FAILED
                state.record_stage_failure(current_stage, exc)
                raise

            current_stage = self.resolve_next_stage(
                definition=definition,
                current_stage=current_stage,
                result=result,
                state=state,
            )

        if state.status == WorkflowStatus.RUNNING:
            state.status = WorkflowStatus.COMPLETED
        return state

    def run_child(
        self,
        *,
        definition: WorkflowDefinition,
        parent_state: WorkflowRunState,
        workflow_input: dict[str, Any],
        environment: Any,
        inherited_artifacts: dict[str, Any] | None = None,
    ) -> SubWorkflowResult:
        child_state = WorkflowRunState(
            workflow_name=definition.name,
            workflow_input=workflow_input,
            parent_run_id=parent_state.run_id,
        )
        for key, value in (inherited_artifacts or {}).items():
            child_state.set_artifact(key, value)
        final_state = self.run(
            definition=definition,
            state=child_state,
            environment=environment,
        )
        recorder = getattr(environment, "child_run_states", None)
        if isinstance(recorder, list):
            recorder.append(final_state)
        return SubWorkflowResult(state=final_state)

    def run_stage(
        self,
        *,
        definition: WorkflowDefinition,
        stage_name: str,
        state: WorkflowRunState,
        environment: Any,
    ) -> StageResult:
        state.current_stage = stage_name
        stage = definition.get_stage(stage_name)
        try:
            stage_context = self.context_assembler.build(
                harness_context=environment,
                workflow_definition=definition,
                workflow_state=state,
                stage=stage,
            )
            stage_input = stage_context.to_stage_input()
            return execute_stage(
                stage=stage,
                context=stage_input,
                run_state=state,
            )
        except Exception as exc:
            failure_stage = getattr(stage, "failure_stage", None) or stage.name
            raise StageExecutionError(failure_stage, exc) from exc

    def apply_stage_result(
        self,
        *,
        definition: WorkflowDefinition,
        stage_name: str,
        result: StageResult,
        state: WorkflowRunState,
    ) -> None:
        state.record_stage_result(stage_name, result)
        if result.signal.type == "terminal_success":
            state.status = WorkflowStatus.SHORT_CIRCUITED
            state.terminal_reason = result.signal.reason
            return
        if result.signal.type == "terminal_failure":
            state.status = WorkflowStatus.FAILED
            state.terminal_reason = result.signal.reason
            return
        if result.success is False:
            stage = definition.get_stage(stage_name)
            state.status = WorkflowStatus.FAILED
            state.terminal_reason = (
                result.observation.code
                if result.observation is not None
                else
                getattr(stage, "terminal_failure_reason", None)
                or f"{stage_name}_failed"
            )
            return
        if stage_name in definition.terminal_stages:
            state.status = WorkflowStatus.COMPLETED

    def resolve_next_stage(
        self,
        *,
        definition: WorkflowDefinition,
        current_stage: str,
        result: StageResult,
        state: WorkflowRunState,
    ) -> str | None:
        self.apply_stage_result(
            definition=definition,
            stage_name=current_stage,
            result=result,
            state=state,
        )
        if state.status in {WorkflowStatus.COMPLETED, WorkflowStatus.SHORT_CIRCUITED}:
            return None
        if state.status == WorkflowStatus.FAILED and result.success:
            return None
        policy = definition.transition_policy or self.transition_policy
        retry_policy = definition.retry_policy or self.retry_policy
        decision = policy.resolve(
            definition=definition,
            stage_name=current_stage,
            result=result,
        )
        next_stage = decision.next_stage
        if result.success is False:
            if (
                result.observation is None
                or not result.observation.retryable
                or next_stage is None
                or decision.rule is None
            ):
                return None
            state.status = WorkflowStatus.RUNNING
            state.terminal_reason = None
        loop_guard = LoopGuard(retry_policy)
        guard = loop_guard.check(
            state=state,
            current_stage=current_stage,
            next_stage=next_stage,
            result=result,
        )
        loop_guard.record(
            state=state,
            current_stage=current_stage,
            next_stage=next_stage,
            result=result,
            decision=decision,
            guard_decision=guard,
        )
        if not guard.allowed:
            state.status = WorkflowStatus.FAILED
            state.terminal_reason = guard.reason
            return None
        return next_stage


LinearWorkflowExecutor = WorkflowRuntime

__all__ = ["LinearWorkflowExecutor", "WorkflowRuntime"]
