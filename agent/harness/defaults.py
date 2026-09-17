from __future__ import annotations

from typing import Any, Callable

from agent.harness.adapters import LegacyCallableWorkflowAdapter, LegacyWorkflowAdapter, WorkflowRuntimeAdapter
from agent.harness.models import WorkflowMetadata
from agent.harness.registry import WorkflowRegistry


def create_default_workflow_registry(
    *,
    value_logic_workflow_factory: Any | None = None,
    value_logic_environment_builder: Callable[..., Any] | None = None,
    value_logic_execute: Callable[..., Any] | None = None,
    expression_execute: Callable[..., Any] | None = None,
    legacy_adapters: dict[str, Callable[..., Any]] | None = None,
) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    legacy_adapters = legacy_adapters or {}
    value_logic_adapter = (
        WorkflowRuntimeAdapter(
            workflow_factory=value_logic_workflow_factory,
            environment_builder=value_logic_environment_builder,
        )
        if value_logic_workflow_factory is not None
        else LegacyCallableWorkflowAdapter(value_logic_execute or expression_execute or _unsupported_value_logic_execute)
    )
    registry.register(
        WorkflowMetadata(
            name="value_logic_generation",
            description="Generate value logic using SQL, BO field, summary, or expression branches.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            visibility="public",
            tags=("value_logic",),
        ),
        value_logic_adapter,
    )
    registry.register(
        WorkflowMetadata(
            name="expression_generation",
            description="Internal expression generation workflow used by value logic generation.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            visibility="internal",
            tags=("expression", "internal"),
        ),
        LegacyCallableWorkflowAdapter(expression_execute or _unsupported_expression_execute),
    )
    registry.register(
        WorkflowMetadata(
            name="sql_value_logic_generation",
            description="Internal SQL value logic child workflow.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            visibility="internal",
            tags=("value_logic", "sql", "internal"),
        ),
        LegacyWorkflowAdapter(_unsupported_internal_child_workflow),
    )
    registry.register(
        WorkflowMetadata(
            name="bo_field_value_logic_generation",
            description="Internal BO field value logic child workflow.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            visibility="internal",
            tags=("value_logic", "bo_field", "internal"),
        ),
        LegacyWorkflowAdapter(_unsupported_internal_child_workflow),
    )
    for name, description, tags in (
        ("node_generation", "Generate a new EDSL node.", ("node", "generation")),
        ("node_modify", "Modify an existing EDSL node.", ("node", "modify")),
        ("ab_data_source_generation", "Generate AB data source configuration.", ("ab", "data_source")),
        ("pdf_parse", "Parse PDF content into structured context.", ("document", "pdf")),
        ("excel_parse", "Parse Excel content into structured context.", ("document", "excel")),
    ):
        registry.register(
            WorkflowMetadata(
                name=name,
                description=description,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                visibility="public",
                legacy=True,
                tags=tags,
            ),
            LegacyWorkflowAdapter(legacy_adapters.get(name)),
        )
    return registry


def _unsupported_expression_execute(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("expression_generation workflow requires an expression_execute adapter")


def _unsupported_value_logic_execute(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("value_logic_generation workflow requires a value_logic_execute adapter")


def _unsupported_internal_child_workflow(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("internal child workflow is executed through ValueLogicWorkflow")
