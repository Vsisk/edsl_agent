from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.workflow.runtime.run_state import WorkflowRunState


@dataclass(frozen=True, slots=True)
class SubWorkflowRequest:
    workflow_name: str
    parent_run_id: str
    workflow_input: dict[str, Any]
    inherited_artifacts: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SubWorkflowResult:
    state: WorkflowRunState


__all__ = ["SubWorkflowRequest", "SubWorkflowResult"]
