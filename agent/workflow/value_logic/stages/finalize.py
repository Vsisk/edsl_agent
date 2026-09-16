from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.workflow.runtime.run_state import WorkflowStatus
from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import StageResult, StageSignal


@dataclass
class FinalizeInput:
    value_logic_result: Any


class FinalizeValueLogicResultStage(Stage):
    name = "finalize"
    input_model = FinalizeInput

    def execute(self, stage_input: FinalizeInput) -> StageResult:
        result = stage_input.value_logic_result
        status = WorkflowStatus.FAILED if getattr(result, "status", None) in {"failed", "need_user_input", "escalate"} else None
        signal = None
        if status == WorkflowStatus.FAILED:
            signal = StageSignal(type="terminal_failure", reason=getattr(result, "status", None))
        return StageResult(outputs={"final_result": result}, signal=signal)


__all__ = ["FinalizeInput", "FinalizeValueLogicResultStage"]
