from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ContextChainType = Literal[
    "namingsql_selection",
    "expression_generation",
    "node_generation",
    "node_modification",
    "context_selection",
]


class BuildContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    project_id: str
    chain_type: ContextChainType = "namingsql_selection"
    query: str
    node: dict[str, Any]
    json_path: str
    target_bo_name: str | None = None
    parent_bo_hint: str | None = None
    target_logic_area_id_list: list[str] = Field(default_factory=list)
    max_context_items: int = 50
    top_k: int = Field(default=5, ge=1, le=20)
    debug: bool = False
