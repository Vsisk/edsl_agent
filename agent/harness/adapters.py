from __future__ import annotations

from typing import Any, Callable

from agent.harness.models import HarnessContext, Operation, OperationResult


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

