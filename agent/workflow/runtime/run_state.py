from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from agent.workflow.runtime.stage_result import ObservationSeverity, StageResult


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    SHORT_CIRCUITED = "short_circuited"
    FAILED = "failed"


@dataclass(slots=True)
class WorkflowRunState:
    workflow_name: str
    workflow_input: dict[str, Any]
    run_id: str = field(default_factory=lambda: str(uuid4()))
    parent_run_id: str | None = None
    status: WorkflowStatus = WorkflowStatus.RUNNING
    terminal_reason: str | None = None
    current_stage: str | None = None
    failed_stage: str | None = None
    failure_error: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    observations: dict[str, Any] = field(default_factory=dict)
    completed_stages: list[str] = field(default_factory=list)
    stage_trace: list[dict[str, Any]] = field(default_factory=list)
    transition_trace: list[dict[str, Any]] = field(default_factory=list)
    stage_attempts: dict[str, int] = field(default_factory=dict)
    failure_fingerprints: dict[str, int] = field(default_factory=dict)
    artifact_fingerprints: dict[str, int] = field(default_factory=dict)

    def set_artifact(self, key: str, value: Any) -> None:
        self.artifacts[key] = value

    def get_artifact(self, key: str, default: Any = None) -> Any:
        return self.artifacts.get(key, default)

    def has_artifact(self, key: str) -> bool:
        return key in self.artifacts

    def require_artifact(self, key: str) -> Any:
        if key not in self.artifacts:
            raise KeyError(f"workflow artifact not found: {key}")
        return self.artifacts[key]

    def record_stage_result(self, stage_name: str, result: StageResult) -> None:
        self.stage_attempts[stage_name] = self.stage_attempts.get(stage_name, 0) + 1
        self.completed_stages.append(stage_name)
        if result.observation is not None:
            self.observations[stage_name] = result.observation
        severity = None
        if result.observation is not None:
            severity = (
                result.observation.severity.value
                if isinstance(result.observation.severity, ObservationSeverity)
                else result.observation.severity
            )
        self.stage_trace.append(
            {
                "stage": stage_name,
                "success": result.success,
                "status": result.status,
                "signal": result.signal.type,
                "reason": result.signal.reason,
                "outputs": sorted(result.outputs.keys()),
                "observation_code": result.observation.code if result.observation else None,
                "severity": severity,
            }
        )

    def record_stage_failure(self, stage_name: str, error: Exception) -> None:
        self.stage_attempts[stage_name] = self.stage_attempts.get(stage_name, 0) + 1
        self.failed_stage = stage_name
        self.failure_error = str(error)
        self.stage_trace.append(
            {
                "stage": stage_name,
                "success": False,
                "signal": "exception",
                "reason": str(error),
                "outputs": [],
            }
        )


__all__ = ["WorkflowRunState", "WorkflowStatus"]
