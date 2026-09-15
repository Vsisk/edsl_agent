from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OperationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class HarnessContext:
    session: Any | None = None
    site_id: str | None = None
    project_id: str | None = None
    project_ref: Any | None = None
    conversation_ref: Any | None = None
    task_ref: Any | None = None
    resource_version: str | None = None
    engineering_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Operation:
    op_id: str
    query: str
    workflow: str
    input: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: OperationStatus = OperationStatus.PENDING
    result_ref: str | None = None
    error: str | None = None


@dataclass(slots=True)
class OperationPlan:
    operations: list[Operation]

    def get(self, op_id: str) -> Operation:
        for operation in self.operations:
            if operation.op_id == op_id:
                return operation
        raise KeyError(f"operation not found: {op_id}")

    def ready_operations(self, completed: set[str]) -> list[Operation]:
        return [
            operation
            for operation in self.operations
            if operation.status == OperationStatus.PENDING
            and all(dep in completed for dep in operation.depends_on)
        ]


@dataclass(frozen=True, slots=True)
class WorkflowMetadata:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    legacy: bool = False
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationResult:
    op_id: str
    workflow: str
    status: OperationStatus
    output: Any = None
    error: str | None = None


@dataclass(slots=True)
class HarnessRunResult:
    plan: OperationPlan
    results: dict[str, OperationResult]

