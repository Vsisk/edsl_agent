from __future__ import annotations

from agent.expression_workflow.core import WorkflowRunState
from agent.expression_workflow.environment import ExpressionExecutionEnvironment
from agent.expression_workflow.executor import WorkflowRuntime
from agent.expression_workflow.result_adapter import ExpressionWorkflowResultAdapter
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
