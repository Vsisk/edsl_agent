from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ValueLogicWorkflowInput:
    site_id: str | None = None
    project_id: str | None = None
    node: dict[str, Any] | None = None
    node_path: str | None = None
    parent_node: dict[str, Any] | None = None
    query: str = ""
    edsl_tree: dict[str, Any] | None = None
    project_type: str | None = None
    is_ab: bool = False
    is_sub_xml: bool = False
    business_scope: str | None = None
    business_path_text: str | None = None
    data_type: dict[str, Any] | None = None
