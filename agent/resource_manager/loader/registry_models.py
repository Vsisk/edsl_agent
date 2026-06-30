from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DataTypeEnum(str, Enum):
    key = "key"
    bo = "bo"
    logic = "logic"
    basic = "basic"
    extattr = "extattr"


class PropertyTypeEnum(str, Enum):
    system = "system"
    custom = "custom"


class SourceType(str, Enum):
    CONTEXT = "context"
    BO = "bo"
    FUNCTION = "function"
    NAMING_SQL = "namingsql"


@dataclass(slots=True)
class FilterTarget:
    source_type: SourceType
    domain: str
    source_name: str
    confidence: float = 1.0
    is_required: bool = True
    reason: str | None = None


@dataclass(slots=True)
class DomainRegistry:
    ctx_domains: list[str] = field(default_factory=list)
    bo_domains: list[str] = field(default_factory=list)
    func_domains: list[str] = field(default_factory=list)
    namingsql_domains: list[str] = field(default_factory=list)


class ReturnType(BaseModel):
    is_list: Optional[bool] = Field(default=None, description="Whether the return value is a list")
    data_type: str = Field(..., description="Return data type")
    data_type_name: Optional[str] = Field(default=None, description="Concrete type name")


class BoReturnField(BaseModel):
    property_name: str = Field("", description="BO field name")
    is_list: bool = Field(False, description="Whether this field is a list")
    annotation: str = Field("", description="Field description")
    return_type: Optional[ReturnType] = None


class ContextRegistry(BaseModel):
    resource_id: str = Field(..., description="Resource id")
    context_name: str = Field(..., description="Context call name, for example $ctx$.xxx.xxx")
    return_type: ReturnType = Field(..., description="Return type")
    property_type: PropertyTypeEnum = Field(..., description="system for built-in context, custom for custom context")
    annotation: str = Field(..., description="Context description with hierarchy")
    tag: list[str] = Field(default_factory=list)


class ParamTerm(BaseModel):
    param_name: str = Field(..., description="Parameter name")
    is_list: bool = Field(default=False, description="Whether this parameter is a list")
    data_type: str = "basic"
    data_type_name: str = Field(..., description="Concrete type name")


class NamingSqlDefTerm(BaseModel):
    naming_sql_id: str = Field(..., description="Named SQL id")
    sql_name: str = Field(..., description="SQL name")
    sql_description: Optional[str] = Field(None, description="SQL description")
    label_name: Optional[str] = Field(None, description="Source label name")
    sql_command: Optional[str] = Field(None, description="Source SQL command")
    param_list: List[ParamTerm] = Field(..., description="Parameter list")


class PropertyTerm(BaseModel):
    field_name: str = Field(..., description="Field name")
    description: Optional[str] = Field(None, description="Description")
    is_list: bool = Field(default=False, description="Whether the return value is a list")
    data_type: DataTypeEnum = Field(..., description="Data type")
    data_type_name: str = Field(..., description="Concrete type name")


class BoRegistry(BaseModel):
    resource_id: str = Field(..., description="Resource id")
    bo_name: str = Field(..., description="BO name")
    bo_desc: str = Field(..., description="BO description")
    property_list: List[PropertyTerm] = Field(..., description="Property list")
    naming_sql_list: List[NamingSqlDefTerm] = Field(default_factory=list, description="Named SQL list")
    tag: list[str] = Field(default_factory=list)


class ParamTypeTerm(BaseModel):
    is_list: bool = Field(default=False, description="Whether this parameter is a list")
    data_type: DataTypeEnum = Field(..., description="Data type")
    data_type_name: Optional[str] = Field(default=None, description="Concrete type name")
    param_name: str = Field(..., description="Parameter name")


class ReturnTypeTerm(BaseModel):
    is_list: bool = Field(default=False, description="Whether the return value is a list")
    data_type: DataTypeEnum = Field(..., description="Data type")
    data_type_name: Optional[str] = Field(default=None, description="Concrete type name")


class FunctionRegistry(BaseModel):
    resource_id: str = Field(..., description="Resource id")
    func_name: str = Field(..., description="Function call name")
    func_desc: str = Field(default="", description="Function description")
    func_class: str = Field(default="", description="Function class")
    param_list: List[ParamTypeTerm] = Field(default_factory=list, description="Parameter list")
    return_type: ReturnTypeTerm = Field(..., description="Return type")
    tag: list[str] = Field(default_factory=list)


class LocalContextRegistry(BaseModel):
    resource_id: str = Field(...)
    context_name: str = Field(...)
    return_type: Optional[ReturnType] = None
    annotation: str = Field(default="")
    source_path: str = Field(default="")
    property_type: str = "local"
    tag: list[str] = Field(default_factory=list)
