from __future__ import annotations

from typing import Any, Callable

from agent.harness.adapters import ExpressionWorkflowAdapter, LegacyWorkflowAdapter
from agent.harness.models import WorkflowMetadata
from agent.harness.registry import WorkflowRegistry


def create_default_workflow_registry(
    *,
    expression_execute: Callable[..., Any] | None = None,
    legacy_adapters: dict[str, Callable[..., Any]] | None = None,
) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    legacy_adapters = legacy_adapters or {}
    registry.register(
        WorkflowMetadata(
            name="expression_generation",
            description="Generate value logic expression for an existing or newly created node.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            tags=("expression", "value_logic"),
        ),
        ExpressionWorkflowAdapter(expression_execute or _unsupported_expression_execute),
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
                legacy=True,
                tags=tags,
            ),
            LegacyWorkflowAdapter(legacy_adapters.get(name)),
        )
    return registry


def _unsupported_expression_execute(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("expression_generation workflow requires an expression_execute adapter")

