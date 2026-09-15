from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent.harness.models import HarnessContext, Operation, OperationResult, WorkflowMetadata


class WorkflowAdapter(Protocol):
    def execute(
        self,
        *,
        operation: Operation,
        context: HarnessContext,
        dependency_results: dict[str, OperationResult],
    ) -> object:
        ...


@dataclass(frozen=True, slots=True)
class WorkflowRegistration:
    metadata: WorkflowMetadata
    adapter: WorkflowAdapter


class WorkflowRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, WorkflowRegistration] = {}

    def register(self, metadata: WorkflowMetadata, adapter: WorkflowAdapter) -> None:
        if metadata.name in self._registrations:
            raise ValueError(f"workflow already registered: {metadata.name}")
        self._registrations[metadata.name] = WorkflowRegistration(
            metadata=metadata,
            adapter=adapter,
        )

    def get(self, workflow_name: str) -> WorkflowRegistration:
        return self._registrations[workflow_name]

    def has(self, workflow_name: str) -> bool:
        return workflow_name in self._registrations

    def metadata(self) -> list[WorkflowMetadata]:
        return [registration.metadata for registration in self._registrations.values()]

