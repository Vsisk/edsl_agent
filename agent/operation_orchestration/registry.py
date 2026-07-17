from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError


ToolHandler = Callable[[BaseModel, Any], Any]
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class OperationToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    mutates_tree: bool = False

    def __post_init__(self) -> None:
        if not _TOOL_NAME.fullmatch(self.name):
            raise ValueError("operation tool name must be snake_case")
        if not self.description.strip():
            raise ValueError("operation tool description must be nonblank")
        if not isinstance(self.input_model, type) or not issubclass(
            self.input_model, BaseModel
        ):
            raise TypeError("operation tool input_model must be a Pydantic model")


@dataclass(frozen=True, slots=True)
class _RegisteredTool:
    spec: OperationToolSpec
    handler: ToolHandler


class OperationToolRegistry:
    """Register, describe, validate, and dispatch operation tools."""

    def __init__(self) -> None:
        self._tools: dict[str, _RegisteredTool] = {}

    def register(self, spec: OperationToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        if not callable(handler):
            raise TypeError("operation tool handler must be callable")
        self._tools[spec.name] = _RegisteredTool(spec=spec, handler=handler)

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> OperationToolSpec:
        registered = self._tools.get(name)
        if registered is None:
            raise ValueError(f"unknown operation tool: {name}")
        return registered.spec

    def tool_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": registered.spec.name,
                "description": registered.spec.description,
                "input_schema": registered.spec.input_model.model_json_schema(),
                "mutates_tree": registered.spec.mutates_tree,
            }
            for registered in self._tools.values()
        ]

    def execute(self, name: str, arguments: Any, context: Any) -> Any:
        registered = self._tools.get(name)
        if registered is None:
            raise ValueError(f"unknown operation tool: {name}")
        try:
            tool_input = registered.spec.input_model.model_validate(
                arguments, strict=True
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid tool input for {name}: {exc}") from exc
        return registered.handler(tool_input, context)
