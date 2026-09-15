from __future__ import annotations

from agent.expression_workflow.context import ContextAssembler
from agent.expression_workflow.core import Stage, WorkflowDefinition, WorkflowRunState
from typing import Any


class StageInputBinder:
    def __init__(self, assembler: ContextAssembler | None = None) -> None:
        self.assembler = assembler or ContextAssembler()

    def bind(
        self,
        *,
        definition: WorkflowDefinition | None = None,
        stage: Stage,
        state: WorkflowRunState,
        environment: Any,
    ):
        stage_context = self.assembler.build(
            harness_context=environment,
            workflow_definition=definition,
            workflow_state=state,
            stage=stage,
        )
        return stage_context.to_stage_input()
