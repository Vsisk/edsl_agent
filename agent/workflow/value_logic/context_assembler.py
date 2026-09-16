from __future__ import annotations

from typing import Any

from agent.workflow.context import HarnessContext


class ValueLogicContextAssembler:
    def __init__(self, environment_builder=None) -> None:
        self.environment_builder = environment_builder

    def build(
        self,
        *,
        harness_context: HarnessContext | Any,
        workflow_input: Any,
        **kwargs: Any,
    ) -> Any:
        if self.environment_builder is None:
            raise RuntimeError("value logic environment_builder is required")
        return self.environment_builder(
            workflow_input=workflow_input,
            context=harness_context,
            **kwargs,
        )


__all__ = ["ValueLogicContextAssembler"]
