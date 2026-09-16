from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from agent.workflow.core import Observation


BranchOutcomeStatus = Literal[
    "success",
    "fallback",
    "failed",
    "need_user_input",
    "escalate",
]


@dataclass(slots=True)
class ValueLogicBranchOutcome:
    status: BranchOutcomeStatus
    branch_type: str
    result: Any | None = None
    fallback_target: str | None = None
    handoff_artifacts: dict[str, Any] = field(default_factory=dict)
    observation: Observation | None = None
    child_run_id: str | None = None
