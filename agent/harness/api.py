from __future__ import annotations

from typing import Any, Callable

from agent.harness.defaults import create_default_workflow_registry
from agent.harness.models import HarnessContext, HarnessRunResult
from agent.harness.runtime import HarnessRuntime


def create_harness_runtime(
    *,
    value_logic_workflow_factory: Any | None = None,
    value_logic_environment_builder: Callable[..., Any] | None = None,
    value_logic_execute: Callable[..., Any] | None = None,
    expression_execute: Callable[..., Any] | None = None,
    legacy_adapters: dict[str, Callable[..., Any]] | None = None,
) -> HarnessRuntime:
    return HarnessRuntime(
        registry=create_default_workflow_registry(
            value_logic_workflow_factory=value_logic_workflow_factory,
            value_logic_environment_builder=value_logic_environment_builder,
            value_logic_execute=value_logic_execute,
            expression_execute=expression_execute,
            legacy_adapters=legacy_adapters,
        )
    )


def handle_harness_request(
    *,
    query: str,
    context: HarnessContext | None = None,
    value_logic_workflow_factory: Any | None = None,
    value_logic_environment_builder: Callable[..., Any] | None = None,
    value_logic_execute: Callable[..., Any] | None = None,
    expression_execute: Callable[..., Any] | None = None,
    legacy_adapters: dict[str, Callable[..., Any]] | None = None,
) -> HarnessRunResult:
    runtime = create_harness_runtime(
        value_logic_workflow_factory=value_logic_workflow_factory,
        value_logic_environment_builder=value_logic_environment_builder,
        value_logic_execute=value_logic_execute,
        expression_execute=expression_execute,
        legacy_adapters=legacy_adapters,
    )
    return runtime.handle(query=query, context=context)
