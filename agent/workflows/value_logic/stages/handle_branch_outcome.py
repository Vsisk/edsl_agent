from __future__ import annotations

from dataclasses import dataclass

from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import Observation, ObservationSeverity, StageResult
from agent.workflows.value_logic.result import ValueLogicBranchOutcome


@dataclass
class HandleOutcomeInput:
    branch_outcome: ValueLogicBranchOutcome
    branch_history: list[str]


class HandleBranchOutcomeStage(Stage):
    name = "handle_outcome"
    input_model = HandleOutcomeInput

    def execute(self, stage_input: HandleOutcomeInput) -> StageResult:
        outcome = stage_input.branch_outcome
        branch_history = list(stage_input.branch_history)
        if outcome.branch_type not in branch_history:
            branch_history.append(outcome.branch_type)

        outputs = {
            "branch_history": branch_history,
            "branch_outcome": outcome,
        }
        if outcome.handoff_artifacts:
            outputs["handoff_artifacts"] = outcome.handoff_artifacts

        if outcome.status == "success":
            outputs["value_logic_result"] = outcome.result
            return StageResult(outputs=outputs)

        if outcome.status == "fallback" and outcome.fallback_target:
            if outcome.fallback_target in branch_history:
                outputs["value_logic_result"] = ValueLogicBranchOutcome(
                    status="failed",
                    branch_type="value_logic",
                    observation=Observation(
                        code="INTERNAL_ERROR",
                        source_stage=self.name,
                        message=f"fallback loop detected for branch: {outcome.fallback_target}",
                        retryable=False,
                        severity=ObservationSeverity.ERROR,
                    ),
                )
                return StageResult(outputs=outputs)
            outputs["active_branch"] = outcome.fallback_target
            return StageResult(outputs=outputs)

        outputs["value_logic_result"] = outcome
        return StageResult(outputs=outputs)


__all__ = ["HandleBranchOutcomeStage", "HandleOutcomeInput"]
