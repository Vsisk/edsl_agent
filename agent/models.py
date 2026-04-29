from pydantic import BaseModel, Field
from typing import Dict, Any


class NodeDef(BaseModel):
    node_id: str
    node_path: str
    node_name: str
    description: str = ""
    is_ab: bool = False
    ab_data_source: dict = Field(default_factory=dict)


class GenerateDSLRequest(BaseModel):
    user_requirement: str = Field(...)
    node: NodeDef = Field(...)
    site_id: str = Field(...)
    project_id: str = Field(...)
    edsl_tree: Dict[str, Any]


class GenerateDSLResponse(BaseModel):
    success: bool
    dsl: str = ""
    failure_reason: str = ""
