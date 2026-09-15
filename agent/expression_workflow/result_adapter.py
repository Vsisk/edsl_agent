from __future__ import annotations

from typing import Any, Callable

from agent.expression_workflow.core import WorkflowRunState, WorkflowStatus


class ExpressionWorkflowResultAdapter:
    def __init__(
        self,
        *,
        result_model: Callable[..., Any],
        source_model: Callable[..., Any],
        agent_status: Any,
        return_type_model: Callable[..., Any],
        node_display_fn: Callable[[Any], str] | None = None,
        report_progress_fn: Callable[[str], None] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.result_model = result_model
        self.source_model = source_model
        self.agent_status = agent_status
        self.return_type_model = return_type_model
        self.node_display_fn = node_display_fn
        self.report_progress_fn = report_progress_fn
        self.logger = logger

    def build(self, state: WorkflowRunState) -> Any:
        if state.terminal_reason == "ootb_override":
            return self._build_ootb(state)

        if (
            state.terminal_reason == "validation_failed"
            or state.get_artifact("validation") is not None
            and state.status == WorkflowStatus.FAILED
        ):
            return self._build_validation_failed(state)

        return self._build_success(state)

    def _build_success(self, state: WorkflowRunState) -> Any:
        request = state.workflow_input["request"]
        final_expression = state.require_artifact("final_expression")
        self._report_expression(request, final_expression)
        return self.result_model(
            status=self.agent_status.SUCCESS,
            logic_type="expression",
            expression=final_expression,
            return_type=state.require_artifact("return_type").model_dump(),
            source=self.source_model(source_type="plan"),
        )

    def _build_ootb(self, state: WorkflowRunState) -> Any:
        request = state.workflow_input["request"]
        ootb = state.require_artifact("ootb_result")
        self._report_expression(request, ootb["expression"])
        return self.result_model(
            status=self.agent_status.SUCCESS,
            logic_type="expression",
            expression=ootb["expression"],
            return_type=ootb["return_type"].model_dump(),
            source=self.source_model(source_type="plan"),
            datatype=ootb["datatype"],
        )

    def _build_validation_failed(self, state: WorkflowRunState) -> Any:
        validation = state.require_artifact("validation")
        observation = state.observations.get("ast_validation") or state.observations.get("validation")
        if self.logger is not None:
            self.logger.error(f"[ValueLogicGenerator] AST validation failed: {validation.errors}")
        validation_errors = list(validation.errors)
        if observation is not None:
            validation_errors = [
                {
                    **(
                        observation.to_dict()
                        if hasattr(observation, "to_dict")
                        else {"code": getattr(observation, "code", "INTERNAL_ERROR")}
                    ),
                    "raw_errors": validation_errors,
                }
            ]
        return self.result_model(
            status=self.agent_status.FAILED,
            logic_type="validation_failed",
            expression="",
            return_type=self.return_type_model().model_dump(),
            source=self.source_model(source_type="plan"),
            validation_errors=validation_errors,
        )

    def _report_expression(self, request: Any, expression: str) -> None:
        if self.report_progress_fn is None:
            return
        node_display = self.node_display_fn(request) if self.node_display_fn is not None else "节点"
        self.report_progress_fn(f"{node_display} 表达式: {expression}")

    def _debug_info(self, state: WorkflowRunState) -> dict[str, Any] | None:
        typed_context = state.get_artifact("typed_context")
        plan = state.get_artifact("plan")
        parsed_plan = state.get_artifact("parsed_plan")
        validation = state.get_artifact("validation")
        return_type = state.get_artifact("raw_return_type")
        if typed_context is None or plan is None:
            return None
        return {
            "typed_context": typed_context.model_dump(mode="json"),
            "simple_plan": plan.model_dump(mode="json") if hasattr(plan, "model_dump") else None,
            "parsed_plan": parsed_plan.model_dump(mode="json") if parsed_plan is not None else None,
            "ast_validation_result": validation.model_dump(mode="json")
            if hasattr(validation, "model_dump")
            else {
                "is_valid": bool(getattr(validation, "is_valid", False)),
                "errors": list(getattr(validation, "errors", []) or []),
            },
            "return_type": return_type.model_dump(mode="json") if hasattr(return_type, "model_dump") else None,
        }
