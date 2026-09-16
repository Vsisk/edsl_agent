from __future__ import annotations

from typing import Any

from agent.workflow.runtime.run_state import WorkflowRunState
from agent.workflow.runtime.stage_result import StageResult


class Stage:
    name: str
    failure_stage: str | None = None
    input_model: type
    context_policy: Any | None = None
    artifact_bindings: dict[str, str] = {}
    optional_artifact_bindings: dict[str, str] = {}
    environment_bindings: dict[str, str] = {}

    def execute(self, stage_input: Any) -> StageResult:
        raise NotImplementedError


class StageExecutionError(Exception):
    def __init__(self, stage: str, error: Exception) -> None:
        super().__init__(str(error))
        self.stage = stage
        self.error = error


def execute_stage(
    *,
    stage: Stage,
    context: Any,
    run_state: WorkflowRunState,
) -> StageResult:
    result = stage.execute(context)
    for key, value in result.outputs.items():
        run_state.set_artifact(key, value)
    return result


__all__ = ["Stage", "StageExecutionError", "execute_stage"]
