from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import StageResult


@dataclass
class RouteInput:
    target: Any | None = None


class RouteValueLogicStage(Stage):
    name = "route"
    input_model = RouteInput

    def execute(self, stage_input: RouteInput) -> StageResult:
        target = stage_input.target
        branch = "expression"
        if target is not None:
            branch = {
                "sql": "sql",
                "table_field": "bo_field",
                "summary": "summary",
            }.get(getattr(target, "primary_branch", None), "expression")
        return StageResult(outputs={"active_branch": branch})


__all__ = ["RouteInput", "RouteValueLogicStage"]
