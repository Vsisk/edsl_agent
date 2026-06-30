from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.operation_orchestration.action_adapter import OperationActionAdapter
from agent.operation_orchestration.executor import OperationExecutor
from agent.operation_orchestration.generator import OperationGenerator
from agent.operation_orchestration.locator import OperationLocator
from agent.operation_orchestration.models import (
    ExecuteOperationsRequest,
    ExecuteOperationsResponse,
    GenerateOperationsRequest,
)


class OperationOrchestrator:
    """Public facade for generating and executing operation graphs."""

    def __init__(
        self,
        generator=None,
        locator=None,
        executor=None,
        action_adapter=None,
    ) -> None:
        self.generator = generator if generator is not None else OperationGenerator()
        if executor is not None:
            self.executor = executor
            return

        chosen_locator = locator if locator is not None else OperationLocator()
        chosen_adapter = (
            action_adapter if action_adapter is not None else OperationActionAdapter()
        )
        self.executor = OperationExecutor(
            locator=chosen_locator,
            action_adapter=chosen_adapter,
        )

    def run(
        self,
        query: str,
        target_tree: dict[str, Any],
        site_id: str | None = None,
        project_id: str | None = None,
    ) -> ExecuteOperationsResponse:
        pristine_tree = deepcopy(target_tree)
        try:
            generated = self.generator.generate(
                GenerateOperationsRequest(
                    query=query,
                    target_tree=deepcopy(pristine_tree),
                )
            )
        except Exception as exc:
            return ExecuteOperationsResponse(
                success=False,
                target_tree=pristine_tree,
                operations=[],
                error_message=f"operation generation failed: {exc}",
            )

        return self.executor.execute(
            ExecuteOperationsRequest(
                operations=generated.operations,
                target_tree=pristine_tree,
                site_id=site_id,
                project_id=project_id,
            )
        )
