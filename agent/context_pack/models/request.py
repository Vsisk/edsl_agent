from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class ResourceName(str, Enum):
    DEV_SKILL = "dev_skill"
    OOTB_EDSL = "ootb_edsl"
    CURRENT_TREE = "current_tree"


class ContextPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: dict[str, Any]
    query: str
    resource_names: list[ResourceName]

    @field_validator("node")
    @classmethod
    def validate_node(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("node must be a non-empty object")
        return value

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value

    @field_validator("resource_names")
    @classmethod
    def validate_resources(cls, value: list[ResourceName]) -> list[ResourceName]:
        result = list(dict.fromkeys(value))
        if not result:
            raise ValueError("resource_names must not be empty")
        return result
