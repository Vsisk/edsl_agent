from typing import Any, Literal

from pydantic import BaseModel, Field


class NodeDef(BaseModel):
    node_id: str
    node_path: str
    node_name: str
    description: str = ""
    is_ab: bool = False
    ab_data_source: dict = Field(default_factory=dict)


class ValueLogicRequest(BaseModel):
    site_id: str
    project_id: str
    node_path: str
    node: dict[str, Any]
    parent_node: dict[str, Any] | None = None
    query: str
    is_ab: bool = False
    edsl_tree: dict[str, Any] | None = None
    structured_spec: dict[str, Any] = Field(default_factory=dict)
    debug: bool = False


class ValueLogicSource(BaseModel):
    source_type: Literal["plan", "bo", "detail_field"]
    bo_name: str | None = None
    bo_field: str | None = None
    detail_field: str | None = None
    summary_type: Literal["sum", "count"] | None = None


class ValueReturnType(BaseModel):
    is_list: bool
    data_type: str
    data_type_name: str


class ValueLogicResult(BaseModel):
    node_id: str | None = None
    logic_type: Literal["expression", "bo_field_mapping", "summary", "validation_failed"]
    expression: str | None = None
    return_type: ValueReturnType | None = None
    source: ValueLogicSource
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    debug_info: dict[str, Any] | None = None
