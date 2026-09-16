from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal
from uuid import uuid4


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    SHORT_CIRCUITED = "short_circuited"
    FAILED = "failed"


class ObservationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


@dataclass(slots=True)
class StageSignal:
    type: Literal["continue", "terminal_success", "terminal_failure"] = "continue"
    reason: str | None = None


@dataclass(slots=True)
class Observation:
    code: str
    source_stage: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    missing_information: list[str] = field(default_factory=list)
    related_artifacts: list[str] = field(default_factory=list)
    retryable: bool = True
    severity: ObservationSeverity | str = ObservationSeverity.ERROR

    def to_dict(self) -> dict[str, Any]:
        severity = self.severity.value if isinstance(self.severity, ObservationSeverity) else self.severity
        return {
            "code": self.code,
            "source_stage": self.source_stage,
            "message": self.message,
            "evidence": self.evidence,
            "missing_information": self.missing_information,
            "related_artifacts": self.related_artifacts,
            "retryable": self.retryable,
            "severity": severity,
        }


@dataclass(slots=True, init=False)
class StageResult:
    status: Literal["succeeded", "failed"]
    outputs: dict[str, Any]
    signal: StageSignal
    observation: Observation | None

    def __init__(
        self,
        success: bool | None = None,
        outputs: dict[str, Any] | None = None,
        signal: StageSignal | None = None,
        observation: Observation | None = None,
        status: Literal["succeeded", "failed"] | None = None,
    ) -> None:
        if status is None:
            status = "succeeded" if success is not False else "failed"
        self.status = status
        self.outputs = outputs or {}
        self.signal = signal or StageSignal()
        self.observation = observation

    @property
    def success(self) -> bool:
        return self.status == "succeeded"


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

    def record_stage_result(self, stage_name: str, result: "StageResult") -> None:
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


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    name: str
    entry_stage: str
    stages: dict[str, Stage]
    default_transitions: dict[str, str | None]
    terminal_stages: set[str] = field(default_factory=set)
    transition_policy: Any | None = None
    retry_policy: Any | None = None

    def get_stage(self, stage_name: str) -> Stage:
        return self.stages[stage_name]


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
