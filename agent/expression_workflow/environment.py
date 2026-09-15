from __future__ import annotations

from typing import Any
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExpressionExecutionEnvironment:
    request: Any
    resources_context: Any
    context_pack: Any
    node_info: Any
    retry_feedback: dict[str, Any] | None = None
    initial_filtered_env: Any | None = None
    query_is_explicit_spec: bool = False
    capability_registries: Any | None = None
