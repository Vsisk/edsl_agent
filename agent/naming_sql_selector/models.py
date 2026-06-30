from pydantic import BaseModel, ConfigDict, Field


class SelectorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NamingSqlParamProfile(SelectorModel):
    name: str
    data_type: str = ""
    is_list: bool = False


class NamingSqlProfile(SelectorModel):
    site_id: str
    bo_name: str
    naming_sql_id: str
    sql_name: str
    label_name: str = ""
    sql_description: str = ""
    params: list[NamingSqlParamProfile] = Field(default_factory=list)
    filter_fields: list[str] = Field(default_factory=list)
    scope_tags: list[str] = Field(default_factory=list)
    is_full_table: bool = True
    search_text: str = ""
