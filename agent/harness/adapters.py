from __future__ import annotations

from typing import Any, Callable

from agent.harness.models import HarnessContext, Operation, OperationResult
from agent.workflow.core import WorkflowRunState
from agent.workflow.executor import WorkflowRuntime


class UnsupportedWorkflowError(RuntimeError):
    pass


class LegacyWorkflowAdapter:
    def __init__(self, execute: Callable[..., Any] | None = None) -> None:
        self._execute = execute

    def execute(
        self,
        *,
        operation: Operation,
        context: HarnessContext,
        dependency_results: dict[str, OperationResult],
    ) -> Any:
        if self._execute is None:
            raise UnsupportedWorkflowError(f"workflow is registered but not implemented: {operation.workflow}")
        return self._execute(
            operation=operation,
            context=context,
            dependency_results=dependency_results,
        )


class ExpressionWorkflowAdapter:
    def __init__(self, execute: Callable[..., Any]) -> None:
        self._execute = execute

    def execute(
        self,
        *,
        operation: Operation,
        context: HarnessContext,
        dependency_results: dict[str, OperationResult],
    ) -> Any:
        expression_input = dict(operation.input)
        expression_input.setdefault("query", operation.query)
        expression_input.setdefault("dependency_results", dependency_results)
        return self._execute(expression_input, context)


class WorkflowRuntimeAdapter:
    def __init__(
        self,
        *,
        workflow_factory: Any,
        environment_builder: Callable[..., Any] | None = None,
        runtime: WorkflowRuntime | None = None,
        result_artifact: str = "final_result",
    ) -> None:
        self.workflow_factory = workflow_factory
        self.environment_builder = environment_builder or _default_environment_builder
        self.runtime = runtime or WorkflowRuntime()
        self.result_artifact = result_artifact

    def execute(
        self,
        *,
        operation: Operation,
        context: HarnessContext,
        dependency_results: dict[str, OperationResult],
    ) -> Any:
        workflow_input = dict(operation.input)
        workflow_input.setdefault("query", operation.query)
        workflow_input.setdefault("dependency_results", dependency_results)
        definition = self.workflow_factory.create_definition()
        state = WorkflowRunState(
            workflow_name=definition.name,
            workflow_input=workflow_input,
        )
        state.workflow_input["parent_state"] = state
        environment = self.environment_builder(
            workflow_input=workflow_input,
            context=context,
            operation=operation,
            dependency_results=dependency_results,
        )
        final_state = self.runtime.run(
            definition=definition,
            state=state,
            environment=environment,
        )
        return final_state.require_artifact(self.result_artifact)


def _default_environment_builder(
    *,
    workflow_input: dict[str, Any],
    context: HarnessContext,
    operation: Operation,
    dependency_results: dict[str, OperationResult],
) -> dict[str, Any]:
    return {
        "request": workflow_input,
        "harness_context": context,
        "operation": operation,
        "dependency_results": dependency_results,
    }
