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
    OperationToolLoopRequest,
    OperationToolLoopResponse,
)
from agent.operation_orchestration.tool_loop import OperationToolLoop


class OperationOrchestrator:
    """Public facade using a tool loop by default with explicit graph compatibility."""

    def __init__(
        self,
        generator=None,
        locator=None,
        executor=None,
        action_adapter=None,
        tool_loop=None,
    ) -> None:
        legacy_dependencies = (generator, locator, executor, action_adapter)
        if tool_loop is not None and any(
            dependency is not None for dependency in legacy_dependencies
        ):
            raise ValueError(
                "tool_loop cannot be combined with legacy dependencies"
            )
        if tool_loop is not None:
            self.tool_loop = tool_loop
            self._uses_tool_loop = True
            return
        if not any(dependency is not None for dependency in legacy_dependencies):
            self.tool_loop = OperationToolLoop()
            self._uses_tool_loop = True
            return

        self._uses_tool_loop = False
        if executor is not None and (locator is not None or action_adapter is not None):
            raise ValueError(
                "executor cannot be combined with locator or action_adapter"
            )
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
        max_steps: int = 20,
    ) -> ExecuteOperationsResponse | OperationToolLoopResponse:
        pristine_tree = deepcopy(target_tree)
        if self._uses_tool_loop:
            try:
                request = OperationToolLoopRequest(
                    query=query,
                    target_tree=deepcopy(pristine_tree),
                    site_id=site_id,
                    project_id=project_id,
                    max_steps=max_steps,
                )
            except Exception:
                return OperationToolLoopResponse(
                    success=False,
                    target_tree=pristine_tree,
                    operations=[],
                    error_message="operation tool request invalid",
                )
            return self.tool_loop.run(request)

        try:
            generated = self.generator.generate(
                GenerateOperationsRequest(
                    query=query,
                    target_tree=deepcopy(pristine_tree),
                )
            )
        except Exception:
            return ExecuteOperationsResponse(
                success=False,
                target_tree=pristine_tree,
                operations=[],
                error_message="operation generation failed",
            )

        return self.executor.execute(
            ExecuteOperationsRequest(
                operations=generated.operations,
                target_tree=pristine_tree,
                site_id=site_id,
                project_id=project_id,
            )
        )
