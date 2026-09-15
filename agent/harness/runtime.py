from __future__ import annotations

from agent.harness.analyzer import RequirementAnalyzer
from agent.harness.models import (
    HarnessContext,
    HarnessRunResult,
    OperationPlan,
    OperationResult,
    OperationStatus,
)
from agent.harness.registry import WorkflowRegistry
from agent.harness.router import WorkflowRouter


class HarnessRuntime:
    def __init__(
        self,
        *,
        registry: WorkflowRegistry,
        analyzer: RequirementAnalyzer | None = None,
        router: WorkflowRouter | None = None,
    ) -> None:
        self.registry = registry
        self.analyzer = analyzer or RequirementAnalyzer()
        self.router = router or WorkflowRouter(registry)

    def handle(
        self,
        *,
        query: str,
        context: HarnessContext | None = None,
        plan: OperationPlan | None = None,
    ) -> HarnessRunResult:
        harness_context = context or HarnessContext()
        operation_plan = plan or self.router.route(
            self.analyzer.analyze(query=query, context=harness_context)
        )
        return self.execute_plan(operation_plan, harness_context)

    def execute_plan(
        self,
        plan: OperationPlan,
        context: HarnessContext,
    ) -> HarnessRunResult:
        completed: set[str] = set()
        results: dict[str, OperationResult] = {}

        while len(completed) < len(plan.operations):
            ready = plan.ready_operations(completed)
            if not ready:
                pending = [
                    operation.op_id
                    for operation in plan.operations
                    if operation.status == OperationStatus.PENDING
                ]
                raise RuntimeError(f"operation dependency cycle or blocked operations: {pending}")
            for operation in ready:
                operation.status = OperationStatus.RUNNING
                registration = self.registry.get(operation.workflow)
                dependency_results = {
                    dependency: results[dependency]
                    for dependency in operation.depends_on
                }
                try:
                    output = registration.adapter.execute(
                        operation=operation,
                        context=context,
                        dependency_results=dependency_results,
                    )
                except Exception as exc:
                    operation.status = OperationStatus.FAILED
                    operation.error = str(exc)
                    result = OperationResult(
                        op_id=operation.op_id,
                        workflow=operation.workflow,
                        status=OperationStatus.FAILED,
                        error=str(exc),
                    )
                    results[operation.op_id] = result
                    completed.add(operation.op_id)
                    self._skip_dependents(plan, operation.op_id, results, completed)
                    continue
                operation.status = OperationStatus.COMPLETED
                operation.result_ref = operation.op_id
                results[operation.op_id] = OperationResult(
                    op_id=operation.op_id,
                    workflow=operation.workflow,
                    status=OperationStatus.COMPLETED,
                    output=output,
                )
                completed.add(operation.op_id)
        return HarnessRunResult(plan=plan, results=results)

    def _skip_dependents(
        self,
        plan: OperationPlan,
        failed_op_id: str,
        results: dict[str, OperationResult],
        completed: set[str],
    ) -> None:
        for operation in plan.operations:
            if operation.status != OperationStatus.PENDING:
                continue
            if failed_op_id not in operation.depends_on:
                continue
            operation.status = OperationStatus.SKIPPED
            operation.error = f"dependency failed: {failed_op_id}"
            results[operation.op_id] = OperationResult(
                op_id=operation.op_id,
                workflow=operation.workflow,
                status=OperationStatus.SKIPPED,
                error=operation.error,
            )
            completed.add(operation.op_id)
