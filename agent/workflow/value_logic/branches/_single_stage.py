from __future__ import annotations

from agent.workflow.context import ContextPolicy
from agent.workflow.runtime.definition import WorkflowDefinition
from agent.workflow.runtime.stage import Stage
from agent.workflow.value_logic.branches.sql.input import BranchWorkflowInput


class SingleStageBranchWorkflowFactory:
    def __init__(self, *, name: str, stage: Stage) -> None:
        self.name = name
        self.stage = stage
        bind_branch_stage(self.stage)

    def create_definition(self) -> WorkflowDefinition:
        return WorkflowDefinition(
            name=self.name,
            entry_stage=self.stage.name,
            stages={self.stage.name: self.stage},
            default_transitions={self.stage.name: None},
            terminal_stages={self.stage.name},
        )


def bind_branch_stage(stage: Stage) -> None:
    stage.input_model = BranchWorkflowInput
    stage.artifact_bindings = {"generation_context": "generation_context"}
    stage.environment_bindings = {"request": "request"}
    stage.context_policy = ContextPolicy(
        input_model=BranchWorkflowInput,
        artifact_bindings=stage.artifact_bindings,
        harness_bindings=stage.environment_bindings,
    )


__all__ = ["SingleStageBranchWorkflowFactory", "bind_branch_stage"]
