from __future__ import annotations

from typing import Any, Callable

from agent.workflows.value_logic.branches._single_stage import SingleStageBranchWorkflowFactory
from agent.workflows.value_logic.branches.sql.stages.resolve_sql import SqlWorkflowStage


def create_sql_workflow_factory(resolve_sql_fn: Callable[[Any, Any], Any | None]) -> SingleStageBranchWorkflowFactory:
    return SingleStageBranchWorkflowFactory(
        name="sql_value_logic_generation",
        stage=SqlWorkflowStage(resolve_sql_fn),
    )


SqlValueLogicWorkflowFactory = create_sql_workflow_factory

__all__ = ["SqlValueLogicWorkflowFactory", "create_sql_workflow_factory"]
