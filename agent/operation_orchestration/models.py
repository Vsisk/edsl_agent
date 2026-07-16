from __future__ import annotations

import heapq
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


IntentType: TypeAlias = Literal[
    "create_node",
    "modify_node",
    "generate_expression",
    "delete_node",
]
OperationStatus: TypeAlias = Literal["pending", "located", "executed", "failed"]


class Operation(BaseModel):
    op_id: str
    query: str
    intent_type: IntentType
    depends_on: list[str] = Field(default_factory=list)
    target_from: str | None = None
    target_jsonpath: str | None = None
    target_node_id: str | None = None
    output_node_id: str | None = None
    status: OperationStatus = "pending"
    error_message: str | None = None


class GenerateOperationsRequest(BaseModel):
    query: str
    target_tree: dict[str, Any]


class GenerateOperationsResponse(BaseModel):
    operations: list[Operation]


class LocateOperationRequest(BaseModel):
    operation: Operation
    target_tree: dict[str, Any]


class LocateOperationResponse(BaseModel):
    success: bool
    operation: Operation
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None


class ExecuteOperationsRequest(BaseModel):
    operations: list[Operation]
    target_tree: dict[str, Any]
    site_id: str | None = None
    project_id: str | None = None


class ExecuteOperationsResponse(BaseModel):
    success: bool
    target_tree: dict[str, Any]
    operations: list[Operation]
    error_message: str | None = None


class _StrictToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchNodesInput(_StrictToolModel):
    query: str = Field(min_length=1, max_length=4096)
    intent_type: IntentType
    limit: int = Field(default=20, ge=1, le=100)


class _TargetToolInput(_StrictToolModel):
    target_node_id: str = Field(min_length=1, max_length=256)
    target_jsonpath: str = Field(min_length=1, max_length=2048)
    candidate_version: int = Field(ge=0)
    query: str = Field(min_length=1, max_length=4096)


class CreateNodeInput(_TargetToolInput):
    pass


class ModifyNodeInput(_TargetToolInput):
    pass


class GenerateExpressionInput(_TargetToolInput):
    pass


class DeleteNodeInput(_TargetToolInput):
    pass


class FinishInput(_StrictToolModel):
    summary: str | None = Field(default=None, max_length=1024)


class ToolDecision(_StrictToolModel):
    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallTrace(BaseModel):
    step: int = Field(ge=0)
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    success: bool
    error_message: str | None = None
    tree_version_before: int = Field(ge=0)
    tree_version_after: int = Field(ge=0)


class OperationToolLoopRequest(_StrictToolModel):
    query: str = Field(min_length=1, max_length=4096)
    target_tree: dict[str, Any]
    site_id: str | None = None
    project_id: str | None = None
    max_steps: int = Field(default=20, ge=1, le=100)


class OperationToolLoopResponse(ExecuteOperationsResponse):
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    tree_version: int = Field(default=0, ge=0)


def validate_and_sort_operations(operations: list[Operation]) -> list[Operation]:
    """Validate operation dependencies and return a stable topological order."""
    operation_by_id: dict[str, Operation] = {}
    input_index: dict[str, int] = {}
    for index, operation in enumerate(operations):
        if operation.op_id in operation_by_id:
            raise ValueError(f"duplicate op_id: {operation.op_id}")
        operation_by_id[operation.op_id] = operation
        input_index[operation.op_id] = index

    for operation in operations:
        if operation.op_id in operation.depends_on:
            raise ValueError(f"operation {operation.op_id} has a self-dependency")
        for dependency in operation.depends_on:
            if dependency not in operation_by_id:
                raise ValueError(
                    f"operation {operation.op_id} has missing dependency: {dependency}"
                )
        if operation.target_from is not None and operation.target_from not in operation.depends_on:
            raise ValueError(
                f"operation {operation.op_id} target_from must be present in depends_on"
            )
        if len(operation.depends_on) > 1 and operation.target_from is None:
            raise ValueError(
                f"operation {operation.op_id} has multiple dependencies and requires target_from"
            )

    indegree = {operation.op_id: len(operation.depends_on) for operation in operations}
    dependents: dict[str, list[str]] = {operation.op_id: [] for operation in operations}
    for operation in operations:
        for dependency in operation.depends_on:
            dependents[dependency].append(operation.op_id)

    ready = [
        (input_index[operation.op_id], operation.op_id)
        for operation in operations
        if indegree[operation.op_id] == 0
    ]
    heapq.heapify(ready)

    sorted_operations: list[Operation] = []
    while ready:
        _, op_id = heapq.heappop(ready)
        sorted_operations.append(operation_by_id[op_id])
        for dependent_id in dependents[op_id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                heapq.heappush(ready, (input_index[dependent_id], dependent_id))

    if len(sorted_operations) != len(operations):
        raise ValueError("operation dependency graph contains a cycle")

    return sorted_operations
