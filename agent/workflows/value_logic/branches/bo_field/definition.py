from __future__ import annotations

from typing import Any, Callable

from agent.workflows.value_logic.branches._single_stage import SingleStageBranchWorkflowFactory
from agent.workflows.value_logic.branches.bo_field.stages.resolve_bo_field import BoFieldWorkflowStage


def create_bo_field_workflow_factory(
    resolve_bo_field_fn: Callable[[Any, Any], Any | None],
) -> SingleStageBranchWorkflowFactory:
    return SingleStageBranchWorkflowFactory(
        name="bo_field_value_logic_generation",
        stage=BoFieldWorkflowStage(resolve_bo_field_fn),
    )


BoFieldWorkflowFactory = create_bo_field_workflow_factory

__all__ = ["BoFieldWorkflowFactory", "create_bo_field_workflow_factory"]
