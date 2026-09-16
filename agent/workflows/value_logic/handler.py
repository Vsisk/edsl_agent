from __future__ import annotations

from agent.workflow.core import WorkflowRunState
from agent.workflow.executor import WorkflowRuntime
from agent.workflows.value_logic.environment import ValueLogicExecutionEnvironment


class ValueLogicWorkflowHandler:
    def __init__(self, *, workflow_factory, runtime: WorkflowRuntime | None = None) -> None:
        self.workflow_factory = workflow_factory
        self.runtime = runtime or WorkflowRuntime()
        self.last_state: WorkflowRunState | None = None

    def execute(self, *, request, environment: ValueLogicExecutionEnvironment):
        definition = self.workflow_factory.create_definition()
        state = WorkflowRunState(
            workflow_name=definition.name,
            workflow_input={"request": request},
        )
        state.workflow_input["parent_state"] = state
        final_state = self.runtime.run(
            definition=definition,
            state=state,
            environment=environment,
        )
        self.last_state = final_state
        return final_state.require_artifact("final_result")
