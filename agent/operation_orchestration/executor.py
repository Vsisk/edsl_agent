from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.operation_orchestration.action_adapter import OperationActionAdapter
from agent.operation_orchestration.locator import OperationLocator
from agent.operation_orchestration.models import (
    ExecuteOperationsRequest,
    ExecuteOperationsResponse,
    LocateOperationRequest,
    Operation,
    validate_and_sort_operations,
)
from agent.operation_orchestration.node_index import (
    NodeLocateCandidate,
    build_node_index,
    is_valid_candidate,
)


class OperationExecutor:
    """Execute an operation graph against a private, incrementally committed tree."""

    def __init__(self, locator=None, action_adapter=None) -> None:
        self._locator = locator if locator is not None else OperationLocator()
        self._action_adapter = (
            action_adapter if action_adapter is not None else OperationActionAdapter()
        )

    def execute(self, request: ExecuteOperationsRequest) -> ExecuteOperationsResponse:
        operations = [operation.model_copy(deep=True) for operation in request.operations]
        current_tree = deepcopy(request.target_tree)

        try:
            execution_order = validate_and_sort_operations(operations)
        except Exception as exc:
            return ExecuteOperationsResponse(
                success=False,
                target_tree=current_tree,
                operations=operations,
                error_message=f"operation graph validation failed: {exc}",
            )

        if not execution_order:
            return ExecuteOperationsResponse(
                success=True, target_tree=current_tree, operations=operations
            )

        operation_by_id = {operation.op_id: operation for operation in operations}
        try:
            current_index = build_node_index(current_tree)
        except Exception as exc:
            operation = execution_order[0]
            return self._runtime_failure(
                current_tree,
                operations,
                operation,
                f"failed to build current node index: {exc}",
            )

        for operation in execution_order:
            try:
                if operation.depends_on:
                    candidate = self._resolve_dependency_target(
                        operation, operation_by_id, current_index
                    )
                    operation.target_node_id = candidate.node_id
                    operation.target_jsonpath = candidate.jsonpath
                    operation.status = "located"
                    operation.error_message = None
                else:
                    candidate = self._locate_root(operation, current_tree, current_index)

                if not is_valid_candidate(operation.intent_type, candidate):
                    raise ValueError(
                        f"target is not a valid candidate for intent {operation.intent_type}"
                    )

                result = self._dispatch(operation, current_tree, request)
                if not isinstance(result, dict):
                    raise ValueError("adapter result must be an object")
                candidate_tree = result.get("target_tree")
                if not isinstance(candidate_tree, dict):
                    raise ValueError("adapter result target_tree must be an object")
                candidate_tree = deepcopy(candidate_tree)
                candidate_index = build_node_index(candidate_tree)

                output_node_id = self._output_node_id(operation, result)
                if not _nonblank(output_node_id):
                    raise ValueError("adapter result output node ID is blank or missing")
                if output_node_id not in candidate_index:
                    raise ValueError(
                        f"adapter result output node ID is absent from resulting index: {output_node_id}"
                    )

                current_tree = candidate_tree
                current_index = candidate_index
                operation.output_node_id = output_node_id
                operation.status = "executed"
                operation.error_message = None
            except Exception as exc:
                return self._runtime_failure(
                    current_tree, operations, operation, exc
                )

        return ExecuteOperationsResponse(
            success=True, target_tree=current_tree, operations=operations
        )

    def _locate_root(
        self,
        operation: Operation,
        current_tree: dict[str, Any],
        current_index: dict[str, NodeLocateCandidate],
    ) -> NodeLocateCandidate:
        response = self._locator.locate(
            LocateOperationRequest(
                operation=operation.model_copy(deep=True),
                target_tree=deepcopy(current_tree),
            )
        )
        if not response.success:
            message = response.error_message or response.operation.error_message
            raise _LocatorFailure(message or "operation location failed")
        located = response.operation
        if (
            located.status != "located"
            or not _nonblank(located.target_node_id)
            or not _nonblank(located.target_jsonpath)
        ):
            raise ValueError(
                "locator success requires located status and both target fields"
            )
        candidate = current_index.get(located.target_node_id)
        if candidate is None or candidate.jsonpath != located.target_jsonpath:
            raise ValueError(
                "locator target fields do not identify the same current candidate"
            )
        operation.target_node_id = candidate.node_id
        operation.target_jsonpath = candidate.jsonpath
        operation.status = "located"
        operation.error_message = None
        return candidate

    @staticmethod
    def _resolve_dependency_target(
        operation: Operation,
        operation_by_id: dict[str, Operation],
        current_index: dict[str, NodeLocateCandidate],
    ) -> NodeLocateCandidate:
        source_id = operation.target_from or operation.depends_on[0]
        upstream = operation_by_id[source_id]
        if upstream.status != "executed" or not _nonblank(upstream.output_node_id):
            raise ValueError(
                f"upstream operation {source_id} was not executed with a nonblank output node ID"
            )
        candidate = current_index.get(upstream.output_node_id)
        if candidate is None:
            raise ValueError(
                f"upstream output node ID is absent from current index: {upstream.output_node_id}"
            )
        return candidate

    def _dispatch(
        self,
        operation: Operation,
        current_tree: dict[str, Any],
        request: ExecuteOperationsRequest,
    ) -> dict[str, Any]:
        path = operation.target_jsonpath
        if operation.intent_type == "create_node":
            return self._action_adapter.create_node(operation.query, path, current_tree)
        if operation.intent_type == "modify_node":
            return self._action_adapter.modify_node(
                operation.query,
                path,
                current_tree,
                site_id=request.site_id,
                project_id=request.project_id,
            )
        if operation.intent_type == "generate_expression":
            return self._action_adapter.generate_expression(
                operation.query,
                path,
                current_tree,
                site_id=request.site_id,
                project_id=request.project_id,
            )
        if operation.intent_type == "delete_node":
            return self._action_adapter.delete_node(path, current_tree)
        raise ValueError(f"unsupported operation intent: {operation.intent_type}")

    @staticmethod
    def _output_node_id(operation: Operation, result: dict[str, Any]) -> Any:
        if operation.intent_type == "create_node":
            return result.get("created_node_id")
        if operation.intent_type in {"modify_node", "generate_expression"}:
            return operation.target_node_id
        if operation.intent_type == "delete_node":
            return result.get("parent_node_id")
        return None

    @staticmethod
    def _runtime_failure(
        current_tree: dict[str, Any],
        operations: list[Operation],
        operation: Operation,
        reason: Exception | str,
    ) -> ExecuteOperationsResponse:
        if isinstance(reason, _LocatorFailure):
            message = str(reason)
        else:
            message = f"operation {operation.op_id} failed: {reason}"
        operation.status = "failed"
        operation.error_message = message
        return ExecuteOperationsResponse(
            success=False,
            target_tree=current_tree,
            operations=operations,
            error_message=message,
        )


class _LocatorFailure(Exception):
    pass


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
