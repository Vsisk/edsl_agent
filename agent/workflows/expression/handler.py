from __future__ import annotations

from agent.workflow.core import WorkflowRunState
from agent.workflow.executor import WorkflowRuntime
from agent.workflows.expression.environment import ExpressionExecutionEnvironment
from agent.workflows.expression.result_adapter import ExpressionWorkflowResultAdapter
from agent.models import ValueLogicRequest, ValueLogicResult


class ExpressionWorkflowHandler:
    def __init__(
        self,
        *,
        workflow_factory,
        runtime: WorkflowRuntime | None = None,
        result_adapter: ExpressionWorkflowResultAdapter,
    ) -> None:
        self.workflow_factory = workflow_factory
        self.runtime = runtime or WorkflowRuntime()
        self.result_adapter = result_adapter

    def execute(
        self,
        *,
        request: ValueLogicRequest,
        environment: ExpressionExecutionEnvironment,
    ) -> ValueLogicResult:
        definition = self.workflow_factory.create_definition()
        state = WorkflowRunState(
            workflow_name=definition.name,
            workflow_input={"request": request},
        )
        final_state = self.runtime.run(
            definition=definition,
            state=state,
            environment=environment,
        )
        return self.result_adapter.build(final_state)
