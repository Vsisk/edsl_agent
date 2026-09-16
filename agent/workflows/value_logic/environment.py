from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ValueLogicExecutionEnvironment:
    request: Any
    child_run_states: list[Any] = field(default_factory=list)
