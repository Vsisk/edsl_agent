from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


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


__all__ = [
    "Observation",
    "ObservationSeverity",
    "StageResult",
    "StageSignal",
]
