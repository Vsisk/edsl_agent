from __future__ import annotations

from typing import Any, Callable

from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import StageResult
from agent.workflows.value_logic.branches.sql.input import BranchWorkflowInput
from agent.workflows.value_logic.result import ValueLogicBranchOutcome


class SqlWorkflowStage(Stage):
    name = "resolve_sql"
    input_model = BranchWorkflowInput

    def __init__(self, resolve_sql_fn: Callable[[Any, Any], Any | None]) -> None:
        self.resolve_sql_fn = resolve_sql_fn

    def execute(self, stage_input: BranchWorkflowInput) -> StageResult:
        result = self.resolve_sql_fn(stage_input.request, stage_input.generation_context)
        if isinstance(result, ValueLogicBranchOutcome):
            outcome = result
        elif result is None:
            outcome = ValueLogicBranchOutcome(
                status="fallback",
                branch_type="sql",
                fallback_target="expression",
                handoff_artifacts=_sql_handoff_artifacts(stage_input.generation_context),
            )
        else:
            outcome = ValueLogicBranchOutcome(
                status="success",
                branch_type="sql",
                result=result,
            )
        return StageResult(outputs={"branch_outcome": outcome})


def _sql_handoff_artifacts(generation_context: Any) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    filtered_env = getattr(generation_context, "filtered_env", None)
    if filtered_env is not None:
        artifacts["initial_filtered_env"] = filtered_env
    context_pack = getattr(generation_context, "context_pack", None)
    naming_sql_hint = _read_naming_sql_hint(context_pack)
    if naming_sql_hint is not None:
        artifacts["naming_sql_hint"] = naming_sql_hint
    return artifacts


def _read_naming_sql_hint(context_pack: Any) -> Any | None:
    if context_pack is None:
        return None
    if isinstance(context_pack, dict):
        return context_pack.get("naming_sql_hint")
    metadata = getattr(context_pack, "metadata", None)
    if isinstance(metadata, dict) and metadata.get("naming_sql_hint") is not None:
        return metadata["naming_sql_hint"]
    return getattr(context_pack, "naming_sql_hint", None)


__all__ = ["SqlWorkflowStage"]
