from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from agent.operation_orchestration.registry import (
    OperationToolRegistry,
    OperationToolSpec,
)


class _SampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: int


def test_registry_validates_and_dispatches_strict_input() -> None:
    calls: list[tuple[_SampleInput, Any]] = []
    context = object()

    def handler(tool_input: _SampleInput, execution_context: Any) -> dict[str, int]:
        calls.append((tool_input, execution_context))
        return {"value": tool_input.value + 1}

    registry = OperationToolRegistry()
    registry.register(
        OperationToolSpec(
            name="sample_tool",
            description="Increment a sample value.",
            input_model=_SampleInput,
        ),
        handler,
    )

    assert registry.execute("sample_tool", {"value": 2}, context) == {"value": 3}
    assert calls == [(_SampleInput(value=2), context)]

    with pytest.raises(ValueError, match="^invalid tool input for sample_tool:"):
        registry.execute("sample_tool", {"value": 2, "extra": True}, context)
    with pytest.raises(ValueError, match="^invalid tool input for sample_tool:"):
        registry.execute("sample_tool", {"value": "2"}, context)
    assert len(calls) == 1


def test_registry_rejects_duplicate_and_invalid_tool_names() -> None:
    registry = OperationToolRegistry()
    spec = OperationToolSpec(
        name="sample_tool",
        description="Sample.",
        input_model=_SampleInput,
    )
    registry.register(spec, lambda *_: {})

    with pytest.raises(ValueError, match="^tool already registered: sample_tool$"):
        registry.register(spec, lambda *_: {})
    with pytest.raises(ValueError, match="snake_case"):
        OperationToolSpec(
            name="SampleTool",
            description="Invalid.",
            input_model=_SampleInput,
        )


def test_registry_lists_serializable_tool_schemas_in_registration_order() -> None:
    registry = OperationToolRegistry()
    registry.register(
        OperationToolSpec(
            name="first_tool",
            description="First.",
            input_model=_SampleInput,
            mutates_tree=True,
        ),
        lambda *_: {},
    )
    registry.register(
        OperationToolSpec(
            name="second_tool",
            description="Second.",
            input_model=_SampleInput,
        ),
        lambda *_: {},
    )

    assert registry.names() == ["first_tool", "second_tool"]
    assert registry.tool_catalog() == [
        {
            "name": "first_tool",
            "description": "First.",
            "input_schema": _SampleInput.model_json_schema(),
            "mutates_tree": True,
        },
        {
            "name": "second_tool",
            "description": "Second.",
            "input_schema": _SampleInput.model_json_schema(),
            "mutates_tree": False,
        },
    ]


def test_registry_rejects_unknown_tool_without_dispatch() -> None:
    registry = OperationToolRegistry()

    with pytest.raises(ValueError, match="^unknown operation tool: missing$"):
        registry.execute("missing", {}, object())
