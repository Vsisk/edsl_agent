from __future__ import annotations

from agent.harness.analyzer import RequirementAnalysis
from agent.harness.models import Operation, OperationPlan
from agent.harness.registry import WorkflowRegistry


class WorkflowRouter:
    def __init__(self, registry: WorkflowRegistry) -> None:
        self.registry = registry

    def route(self, analysis: RequirementAnalysis) -> OperationPlan:
        operations: list[Operation] = []
        previous_op_id: str | None = None
        for index, workflow in enumerate(analysis.workflows, start=1):
            if not self.registry.has(workflow):
                raise KeyError(f"workflow not registered: {workflow}")
            op_id = f"op_{index}"
            operation_input = dict(analysis.inputs.get(workflow, {}))
            operation_input.setdefault("query", analysis.query)
            operations.append(
                Operation(
                    op_id=op_id,
                    query=analysis.query,
                    workflow=workflow,
                    input=operation_input,
                    depends_on=[previous_op_id] if previous_op_id else [],
                )
            )
            previous_op_id = op_id
        return OperationPlan(operations=operations)

