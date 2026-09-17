from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import StageResult


@dataclass
class PrepareInput:
    request: Any


class PrepareValueLogicStage(Stage):
    name = "prepare"
    input_model = PrepareInput

    def __init__(self, prepare_context_fn: Callable[[Any], tuple[Any, Any | None]]) -> None:
        self.prepare_context_fn = prepare_context_fn

    def execute(self, stage_input: PrepareInput) -> StageResult:
        generation_context, target = self.prepare_context_fn(stage_input.request)
        return StageResult(
            outputs={
                "generation_context": generation_context,
                "target": target,
                "branch_history": [],
            }
        )


__all__ = ["PrepareInput", "PrepareValueLogicStage"]
