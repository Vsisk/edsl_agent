from __future__ import annotations

from dataclasses import dataclass, field

from agent.workflow.runtime.stage import Stage


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    name: str
    entry_stage: str
    stages: dict[str, Stage]
    default_transitions: dict[str, str | None]
    terminal_stages: set[str] = field(default_factory=set)
    transition_policy: object | None = None
    retry_policy: object | None = None

    def get_stage(self, stage_name: str) -> Stage:
        return self.stages[stage_name]


__all__ = ["WorkflowDefinition"]
