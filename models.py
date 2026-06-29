from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict, AliasChoices
from typing import List, Dict, Any, Literal, Optional, Union, Annotated

from common.utils.id_generator import generate_id


class StrictModel(BaseModel):
    def to_dict(self):
        return self.model_dump(exclude_none=True)


class LogicSectionType(str, Enum):
    fields = "fields"
    ab_pivot_table = "ab_pivot_table"
    ab_two_level_table = "ab_two_level_table"
    table = "table"
    picture = "picture"
    others = "others"


class PageMargin(StrictModel):
    top: float = Field(2.0, description="页边距顶部，单位厘米(cm)")
    bottom: float = Field(2.0, description="页边距底部，单位厘米(cm)")
    left: float = Field(2.0, description="页边距左侧，单位厘米(cm)")
    right: float = Field(2.0, description="页边距右侧，单位厘米(cm)")


class CustomPageSize(StrictModel):
    height: float = Field(..., description="自定义页面高度，单位厘米(cm)")
    width: float = Field(..., description="自定义页面宽度，单位厘米(cm)")


class LocationTerm(StrictModel):
    """
    section区域范围定义
    """
    left: float = Field(0.0, description="左边界 x 坐标")
    bottom: float = Field(0.0, description="下边界 y 坐标")
    right: float = Field(0.0, description="右边界 x 坐标")
    top: float = Field(0.0, description="上边界 y 坐标")

class CandidateTermItem(StrictModel):
    candidate_term_id: str = Field(default="", description="候选术语id")
    candidate_term: str = Field(default="", description="候选术语名称")
    candidate_term_confidence: str = Field(default="", description="候选CBS术语对应的置信度评级")

class CBSTermItem(StrictModel):
    cbs_term_id: str = Field(default="", description="CBS术语id")
    cbs_term: str = Field(default="", description="CBS术语名称")
    confidence: str = Field(default="", description="置信度评级")
    original_text: str = Field(default="", description="原始需求中的术语")
    candidate_term_list: List[CandidateTermItem] = Field(default_factory=list, description="候选术语列表")

class NLItem(StrictModel):
    role: str = Field(default="SA", description="角色，可选值: SA, SE")
    nl: str = Field(default="", description="自然语言内容")
    cbs_terms: List[CBSTermItem] = Field(default_factory=list, description="CBS术语列表")

class EdslSemiStructTerm(StrictModel):
    """
    半结构化内容
    """
    trust: str = Field(default="nl", description="信任类型，可选值: dsl, nl")
    nl: List[NLItem] = Field(default_factory=list, description="自然语言片段列表，每个元素包含 role 和 nl 字段")

    def to_dict(self) -> dict:
        return {
            "trust": self.trust,
            "nl": [item.model_dump() for item in self.nl]
        }

    def add_nl(self, role, nl, cbs_terms: Optional[List[Dict]] = None):
        if self.nl is None:
            self.nl = []

        nl_info = NLItem(
            role=role,
            nl=nl,
            cbs_terms=cbs_terms if isinstance(cbs_terms, list) else []
        )
        self.nl.append(nl_info)

    def extract_sa_nl(self, xml_node: dict[str, Any]):
        """
        提取role=SA的edsl_semi_struct

        Args:
            xml_node: XML节点

        Returns:
            role=SA的NL项列表
        """
        edsl_semi_struct = xml_node.get("edsl_semi_struct", {})
        nl_items = edsl_semi_struct.get("nl", [])

        # 筛选role=SA的项
        for item in nl_items:
            if isinstance(item, dict) and item.get("role", "").upper() == "SA":
                self.add_nl(nl=item.get("nl", ""), role="SA")


class EdslPromptTerm(StrictModel):
    prompt: str = Field("", description="LLM 辅助生成时使用的 prompt 内容")


class DataExpressionTerm(StrictModel):
    """
    表达式项：用于定义字段取值逻辑，支持 edsl_expression 或 cdsl。
    """
    expression_type: Literal["edsl_expression", "cdsl"] = Field(default="edsl_expression")

    expression: Optional[str] = None
    cdsl: Optional[str] = None

    @model_validator(mode="after")
    def check_exclusive_fields(self):
        # 根据类型强制检查对应字段是否存在
        if self.expression_type == "edsl_expression":
            if self.expression is None:
                self.expression = ''
            if self.cdsl is not None:
                self.cdsl = None

        elif self.expression_type == "cdsl":
            if self.cdsl is None:
                self.cdsl = ''
            if self.expression is not None:
                self.expression = None

        return self

    def to_dict(self) -> dict:
        return self.model_dump(exclude_unset=True, exclude_none=True)


class DataTypeTerm(StrictModel):
    """
    数据类型。
    """
    data_type: str = Field("simple_string")

    # 条件性字段：当 data_type 为 "time" 时，必须提供以下字段
    region_id_expression: Optional[str] = None
    time_format_expression: Optional[str] = None

    # 条件性字段：当 data_type 为 "money" 时，必须提供以下字段
    currency_id_expression: Optional[str] = None
    int_delimiter_expression: Optional[str] = None
    intp_delimiter_expression: Optional[str] = None
    round_method_expression: Optional[str] = None
    currency_unit: Optional[str] = None
    decimal_precision: Optional[str] = None
    zero_padding: Optional[str] = None

    @model_validator(mode="after")
    def generate(self):
        # 1. 定义依赖关系表
        requirements = {
            "time": ["region_id_expression", "time_format_expression"],
            "money": ["currency_id_expression", "int_delimiter_expression", "intp_delimiter_expression",
                      "round_method_expression", "currency_unit", "decimal_precision", "zero_padding"]
        }

        current_type = self.data_type

        if current_type in requirements:
            for field in requirements[current_type]:
                value = getattr(self, field, None)
                if value == "$default$":
                    object.__setattr__(self, field, None)
                # 如果值是空字符串，也补默认值
                elif isinstance(value, str) and value.strip() == "":
                    object.__setattr__(self, field, None)

        # 3. 清理：将不属于当前类型的字段设为 None
        all_conditional_fields = [f for sublist in requirements.values() for f in sublist]
        allowed_fields = requirements.get(current_type, [])

        for field in all_conditional_fields:
            if field not in allowed_fields and getattr(self, field, None) is not None:
                object.__setattr__(self, field, None)

        return self


class XmlNamePropertyTerm(StrictModel):
    xml_name: Optional[str] = Field(
        None,
        description="可空，未配置不输出XML节点，如：CAT_SUMMARY"
    )
    xml_format_type: str = Field(
        "label",
        description="label-输出为XML标签, property-不输出，只做为属性",
        title="XML格式类型"
    )
    xml_empty_field_type: str = Field(
        "full",
        description="none-[空], half-[<a/>], full-[<a></a>]",
        title="XML空字段类型"
    )

    @field_validator('xml_format_type')
    @classmethod
    def validate_xml_format_type(cls, v: str) -> str:
        valid_values = ["label", "property"]
        if v not in valid_values:
            raise ValueError(f"无效的 xml_format_type 值：{v}。必须是以下之一：{valid_values}")
        return v

    @field_validator('xml_empty_field_type')
    @classmethod
    def validate_xml_empty_field_type(cls, v: str) -> str:
        valid_values = ["none", "half", "full"]
        if v not in valid_values:
            raise ValueError(f"无效的 xml_empty_field_type 值：{v}。必须是以下之一：{valid_values}")
        return v


class XmlNodePropertyTerm(StrictModel):
    node_id: str = Field(default_factory=lambda: generate_id(), title="唯一标识符")
    xml_name_property: XmlNamePropertyTerm = Field(default_factory=lambda: XmlNamePropertyTerm())


class SqlParamsTerm(StrictModel):
    param_name: str = Field(...)
    param_value: str = Field(...)


class NamingSqlTerm(StrictModel):
    """
    命名 SQL 模板定义，用于封装可复用的 SQL 查询逻辑。
    支持动态条件注入与扩展过滤，适用于配置化查询场景。
    """
    naming_sql: str = Field("", title="namingSQL名称")
    sql_conditions: Optional[List[SqlParamsTerm]] = Field(
        default_factory=list,
        title="sql查询条件",
        description="namingSQL对应的查询条件取值，需要保证参数个数、顺序与namingSQL定义一致。"
    )
    ext_conditions: Optional[List[Dict]] = Field(
        default_factory=list,
        title="扩展过滤条件",
        description="可用于附加过滤逻辑，如白名单校验。"
    )

    def set_condition(self, condition_list):
        for condition in condition_list:
            condition_info = SqlParamsTerm(param_name=condition.get("param_name"), param_value=condition.get("value"))
            self.sql_conditions.append(condition_info)


class NamingSqlTermV2(StrictModel):
    type: Literal["REAL", "HOT", "TEST", "RE"] = "REAL"
    naming_sql_content: NamingSqlTerm = NamingSqlTerm()


class SqlQueryTermV2(StrictModel):
    """
    SQL 查询信息定义（v2），支持全量查询与按类型分组查询两种模式。
    根据 is_all 字段动态决定有效结构。
    """
    bo_name: str = Field("", title="需要查询的表的名称")
    is_all: bool = Field(False, description="是否为全量查询")

    # 条件字段（根据 is_all 决定）
    naming_sql_content: Optional[NamingSqlTerm] = None
    naming_sql_list: Optional[List[NamingSqlTermV2]] = None

    @model_validator(mode="after")
    def validate_conditional_fields(self) -> "SqlQueryTermV2":
        if self.is_all:
            # is_all = true 时：必须提供 naming_sql、sql_conditions、ext_conditions
            if not isinstance(self.naming_sql_content, NamingSqlTerm):
                self.naming_sql_content = NamingSqlTerm()
            if self.naming_sql_list:
                self.naming_sql_list = None
        else:
            if not isinstance(self.naming_sql_list, list):
                self.naming_sql_list = []
                self.naming_sql_list.append(NamingSqlTermV2())
            if self.naming_sql_content:
                self.naming_sql_content = None

        return self


class DataSourceTerm(StrictModel):
    """
    数据源定义，支持 SQL 查询或表达式两种类型。
    根据 data_source_type 动态决定有效字段。
    """
    data_source_type: Literal["sql", "expression"] = Field("expression", description="数据源类型")

    # 条件字段（根据 data_source_type 选择性存在）
    sql_query: Optional[SqlQueryTermV2] = None
    data_expression: Optional[DataExpressionTerm] = None

    @model_validator(mode="after")
    def validate_conditional_fields(self) -> "DataSourceTerm":
        if self.data_source_type == "sql" and self.sql_query is None:
            self.sql_query = SqlQueryTermV2()
        if self.data_source_type == "expression" and self.data_expression is None:
            self.data_expression = DataExpressionTerm()
        return self


class SupportBigCustAcctTerm(StrictModel):
    support_big_cust_acct: bool = Field(False)
    data_source: DataSourceTerm = Field(default_factory=lambda: DataSourceTerm())


class LocalContextTerm(StrictModel):
    """
    属性上下文定义，用于描述节点中局部上下文变量的信息。
    """
    property_id: str = Field(..., description="属性唯一标识")
    property_name: str = Field(..., description="属性名称")
    annotation: Optional[str] = Field(None, title="属性的注释信息")
    data_source: DataExpressionTerm = Field(..., title="取值类型")


class XmlNameLevelTerm(StrictModel):
    """
    XML 名称层级项，用于描述汇总层级中的 XML 标题名称和局部上下文。
    """
    xml_node_property: XmlNodePropertyTerm = Field(default_factory=lambda: XmlNodePropertyTerm(),
                                                   description="XML 节点属性")
    local_context: List[LocalContextTerm] = Field(default_factory=list, description="局部上下文列表")


class DataSourceConfig(StrictModel):
    data_source_type: str = Field("expression", description="数据来源类别")

    # 条件字段（仅在对应 data_source_type 时生效）
    table_field_name: Optional[str] = Field(
        "",
        title="非虚拟字段对应的表字段",
        description="当 data_source_type 为 'table_field' 时，该字段必须存在且非空。"
    )
    data_expression: Optional[DataExpressionTerm] = Field(
        default_factory=lambda: DataExpressionTerm(),
        title="使用edsl expression表达的字段取值逻辑",
        description="当 data_source_type 为 'data_expression' 时，该字段必须存在且非空。"
    )

    # 校验：确保仅允许一个分支字段:
    @model_validator(mode="after")
    def validate_data_source_branch(self):
        if self.data_source_type == "table_field":
            if not self.table_field_name:
                self.table_field_name = ""
            if self.data_expression is not None:
                self.data_expression = None
        elif self.data_source_type == "expression":
            if not self.data_expression:
                self.data_expression = DataExpressionTerm()
            if self.table_field_name is not None:
                self.table_field_name = None
        else:
            raise ValueError(f"不支持的 data_source_type: {self.data_source_type}")
        return self


class SummaryField(StrictModel):
    field_id: str = Field(default_factory=lambda: generate_id())
    xml_name_property: XmlNamePropertyTerm = Field(...)
    xml_rank: int = Field(default=0)
    annotation: Optional[str] = Field("", title="节点有关信息注释")
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=lambda: EdslSemiStructTerm(),
                                                 json_schema_extra={"x_llm_generated": False})
    edsl_prompt: EdslPromptTerm = Field(default_factory=lambda: EdslPromptTerm(),
                                        json_schema_extra={"x_llm_generated": False})
    summary_type: str = Field("sum", title="汇总方式")
    support_big_cust_acct: SupportBigCustAcctTerm = Field(default_factory=lambda: SupportBigCustAcctTerm())

    # 用于 sum 汇总方式的字段（条件字段）
    related_detail_field_name: Optional[str] = Field(
        "",
        title="sum汇总方式中，对应汇总的子表字段名称"
    )

    # 用于 count 汇总方式的字段（条件字段）
    related_detail_field_number: Optional[int] = Field(
        0,
        title="count汇总方式中，对应的计数字段数值"
    )

    @model_validator(mode="after")
    def validate_conditions(self) -> "SummaryField":
        if self.summary_type == "sum":
            if not self.related_detail_field_name:
                self.related_detail_field_name= ""
            if self.related_detail_field_number is not None:
                self.related_detail_field_number = None

        elif self.summary_type == "count":
            if self.related_detail_field_name is not None:
                self.related_detail_field_number = None
            if self.related_detail_field_number is None:
                self.related_detail_field_name = 0

        return self


class CommonFieldTerm(StrictModel):
    field_id: str = Field(default_factory=lambda: generate_id())
    xml_name_property: XmlNamePropertyTerm = Field(...)
    xml_rank: int = Field(default=0)
    annotation: Optional[str] = Field("", title="节点有关信息注释")
    data_type_config: Optional[DataTypeTerm] = Field(default_factory=lambda: DataTypeTerm())
    data_source: DataSourceConfig = Field(default_factory=lambda: DataSourceConfig(), title="数据来源")
    support_big_cust_acct: SupportBigCustAcctTerm = Field(default_factory=lambda: SupportBigCustAcctTerm())
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=lambda: EdslSemiStructTerm(),
                                                 json_schema_extra={"x_llm_generated": False})
    edsl_prompt: EdslPromptTerm = Field(default_factory=lambda: EdslPromptTerm(),
                                        json_schema_extra={"x_llm_generated": False})


class SingleMappingTableTerm(StrictModel):
    """
    “简单映射表”项

    简单映射表，字段来自于同一个表。
    """
    tree_node_type: Literal["ab_single_mapping_table"] = Field(default="ab_single_mapping_table", exclude=True)
    data_source: DataSourceTerm = Field(default_factory=lambda: DataSourceTerm(), title="数据源")
    support_big_cust_acct: SupportBigCustAcctTerm = Field(default_factory=lambda: SupportBigCustAcctTerm())
    detail_fields: List[CommonFieldTerm] = Field(
        default_factory=list,
        title="详细字段",
        description="需要在映射表中展示的详细字段列表。"
    )


class PivotTableGroupRegion(StrictModel):
    group_xml_node_property: XmlNodePropertyTerm = Field(default_factory=lambda: XmlNodePropertyTerm(), title="分组节点XML属性")
    support_big_cust_acct: SupportBigCustAcctTerm = Field(default_factory=lambda: SupportBigCustAcctTerm())
    group_related_fields: List[CommonFieldTerm] = Field(
        default_factory=list,
        title="组别相关字段",
        description="每组在xml中显示的、描述组别信息的字段"
    )
    sum_fields: List[CommonFieldTerm] = Field(
        default_factory=list,
        title="汇总字段",
        description="每组需要进行汇总得到的字段"
    )


class TwoLevelTableGroupRegion(StrictModel):
    group_xml_node_property: XmlNodePropertyTerm = Field(default_factory=lambda: XmlNodePropertyTerm(), title="分组节点XML属性")
    support_big_cust_acct: SupportBigCustAcctTerm = Field(default_factory=lambda: SupportBigCustAcctTerm())
    group_related_fields: List[CommonFieldTerm] = Field(
        default_factory=list,
        title="组别相关字段",
        description="每组在xml中显示的、描述组别信息的字段"
    )
    summary_fields: List[SummaryField] = Field(
        default_factory=list,
        title="汇总字段",
        description="每组需要进行汇总得到的字段"
    )

class DetailRegion(StrictModel):
    detail_field_title_xml_name: Optional[XmlNodePropertyTerm] = Field(default_factory=lambda: XmlNodePropertyTerm(),
                                                                       title="详细字段标题XML名称")
    detail_fields: List[CommonFieldTerm] = Field(
        default_factory=list,
        title="详细字段",
        description="分组汇总表中需要展示的详细字段"
    )


class TwoLevelTableTerm(StrictModel):
    """
    分组汇总表，仅支持单层分组，但支持每个组别有额外描述字段。
    """
    tree_node_type: Literal["ab_two_level_table"] = Field(default="ab_two_level_table", exclude=True)
    data_source: DataSourceTerm = Field(default_factory=lambda: DataSourceTerm(), title="数据源")
    group_by_fields: List[CommonFieldTerm] = Field(
        default_factory=list,
        title="分组字段",
        description="用于分组的字段（不一定显示在xml中），决定了分组方式"
    )
    group_region: Optional[TwoLevelTableGroupRegion] = Field(default_factory=lambda: TwoLevelTableGroupRegion())
    detail_region: Optional[DetailRegion] = Field(default_factory=lambda: DetailRegion())
    support_big_cust_acct: SupportBigCustAcctTerm = Field(default_factory=lambda: SupportBigCustAcctTerm())

    model_config = ConfigDict(extra="forbid")  # 禁止额外属性


class PivotTableTerm(StrictModel):
    tree_node_type: Literal["ab_pivot_table"] = Field(default="ab_pivot_table", exclude=True)
    data_source: DataSourceTerm = Field(default_factory=lambda: DataSourceTerm(), title="数据源", description="分组汇总表的数据来源")
    group_by_fields: List[CommonFieldTerm] = Field(
        default_factory=list, title="分组字段", description="用于分组的字段列表（不一定显示在 XML 中）"
    )
    xml_name_for_each_level: List[XmlNameLevelTerm] = Field(
        default_factory=list, title="各层级 XML 标题名称",
        description="列表里 xml 名称顺序为从顶层向下。缺少的层级 xml 名称将使用默认值。\n有多少 list 就有多少个层级，这里仅标识各层级标签名称，data_type 定义为 simple_string"
    )
    group_region: Optional[PivotTableGroupRegion] = Field(default_factory=lambda: PivotTableGroupRegion())


class SimpleFieldTerm(StrictModel):
    field_id: str = Field(
        ...,
        title="字段标识号",
        description="20位字符串，应保证全局唯一。前12位是yyyyMMddHHmm格式的时间，后8位是随机数。",
        json_schema_extra={"x_llm_generated": False}
    )
    xml_name_property: XmlNamePropertyTerm = Field(...)
    annotation: Optional[str] = Field(None, title="节点有关信息注释")
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=lambda: EdslSemiStructTerm(), json_schema_extra={"x_llm_generated": False})
    edsl_prompt: EdslPromptTerm = Field(default_factory=lambda: EdslPromptTerm(), json_schema_extra={"x_llm_generated": False})
    data_expression: DataExpressionTerm = Field(default_factory=lambda: DataExpressionTerm())
    data_type_config: Optional[DataTypeTerm] = Field(default_factory=lambda: DataTypeTerm())
    target_xml_path: Optional[str] = Field(
        None,
        title="对应xml路径（指定xml结构case时）"
    )


class LocationAndPageNum(StrictModel):
    page_number: int = Field(...)
    location: LocationTerm = Field(...)


class LocationItem(StrictModel):
    location_id: str = Field(default_factory=lambda: generate_id())
    reference_instance_id: str = Field(
        default="",
        validation_alias=AliasChoices("reference_instance_id", "reference_pdf_instance_id"),
        serialization_alias="reference_pdf_instance_id"
    )
    page_number: int = Field(...)
    location: LocationTerm = Field(...)
    raw_pdf_text_list: List[str] = Field(default_factory=list)


class ContainedFields(StrictModel):
    pdf_field_name: str = Field(...)
    field_xml_name: str = Field(...)
    sample: str = ""
    field_id: str = ""


class SimpleNodeRefTerm(StrictModel):
    field_id: Optional[str] = Field(default_factory=generate_id)
    pdf_field_name: str = Field("")
    reference_node_id: str = Field("")
    reference_node_xml_name: str = Field("")
    sample: str = ""
    confidence: float = 0.0
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=lambda: EdslSemiStructTerm(),
                                                 json_schema_extra={"x_llm_generated": False})


class FeeCategoryInfo(BaseModel):
    fee_category_name: str = Field("root")
    pdf_field_name: str = ""
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)
    is_display_name: bool = True


class GroupInfo(BaseModel):
    is_group: bool = True
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)


class FeeSummaryField(BaseModel):
    field_ids: list[str] = Field(default_factory=list)
    field_name: str = ""
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)
    summary_type: Literal["count", "sum"] = "sum"
    is_virtual: bool = False


class SummaryInfo(BaseModel):
    summary_title: str
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)
    summary_fields: list[FeeSummaryField] = Field(default_factory=list)
    is_display_title: bool = True


class ChildrenSortRule(BaseModel):
    is_sort: bool = True
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)


class Column(BaseModel):
    field_id: str = Field(default_factory=lambda: generate_id())
    pdf_field_name: str
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=lambda: EdslSemiStructTerm())
    is_sum: bool = True
    field_samples: List[str] = Field(default_factory=list)
    cbs_name: str = ""
    logic_data_node: CommonFieldTerm | FeeSummaryField | None = Field(None, exclude=True)
    module_path: str = Field("", exclude=True)
    seq: int = 0


class FeeCategoryType(str, Enum):
    parent = "parent"
    leaf = "leaf"


class FeeCategoryTerm(BaseModel):
    fee_category_id: str = Field(default_factory=lambda: generate_id())
    fee_category_type: str = Field("parent")
    seq: int = Field(1)
    fee_category_info: FeeCategoryInfo = Field(default_factory=FeeCategoryInfo)
    group_info: GroupInfo = Field(default_factory=lambda: GroupInfo())
    summary_info: list[SummaryInfo] = Field(default_factory=list)
    children_sort_rule: ChildrenSortRule = Field(default_factory=lambda: ChildrenSortRule())
    columns: list[Column] | None = None
    reference_node_id: Optional[str] = None
    children: Optional[list["FeeCategoryTerm"]] = None
    logic_data_node: Optional["TreeNodeTerm"] = Field(None, exclude=True)
    closed: bool = Field(default=False, exclude=True)


    @model_validator(mode="after")
    def validate_conditions(self) -> "FeeCategoryTerm":
        if self.fee_category_type == FeeCategoryType.leaf:
            if self.columns is None:
                self.columns = []
        elif self.fee_category_type == FeeCategoryType.parent:
            if self.children is None:
                self.children = []
        return self

    def get_all_leaf_columns(self) -> List[Column]:
        """
        递归获取当前节点及其所有子节点下的 leaf columns。
        """
        result_columns: List[Column] = []

        if self.fee_category_type == "leaf":
            if self.columns:
                result_columns.extend(self.columns)

        elif self.fee_category_type == "parent":
            if self.children:
                for child in self.children:
                    result_columns.extend(child.get_all_leaf_columns())

        return result_columns

    def to_dict(self):
        return self.model_dump(exclude_none=True)


class SimpleTableTerm(BaseModel):
    reference_list: List[SimpleNodeRefTerm] = Field(default_factory=list)
    reference_node_id: str = Field(default="", description="指向 parent_list 类型的 TreeNode")
    iter_rules: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)
    summary_info: List[SummaryInfo] = Field(default_factory=list)

    parent_list_idx: int = Field(0, exclude=True)
    parent_node: "TreeNodeTerm" = Field(..., exclude=True)

    def get_all_leaf_columns(self) -> List[Column]:
        result_columns: List[Column] = []

        for node in self.reference_list:
            result_columns.append(
                Column(
                    field_id=node.field_id,
                    pdf_field_name=node.pdf_field_name,
                    cbs_name=node.reference_node_xml_name
                )
            )

        return result_columns

class LogicSectionTerm(StrictModel):
    logic_area_id: str = Field(default_factory=lambda: generate_id())
    logic_area_name: str = Field("", description="逻辑区域名称")
    logic_area_description: str = Field("", description="逻辑区域描述")
    logic_area_type: str = Field("field", description="逻辑区域类型")
    cbs_area_type: str = Field("field", description="对应的cbs区域类型")
    layout_description: str = ""
    location_list: List[LocationItem] = Field(default_factory=list, description="位置列表")
    children: List["LogicSectionTerm"] = Field(default_factory=list, description="子logic_area列表")
    reference_list: Optional[List[Dict]] = None
    requirement: Optional[FeeCategoryTerm | SimpleTableTerm] = None

    block_type: str = Field(None, exclude=True)
    source_data: str = Field("", exclude=True)
    section_items_with_requirement: Dict = Field(default={}, exclude=True)

    def set_name(self, index: int, name: str):
        if not name:
            self.logic_area_name = f"New_Section_{index}"
        else:
            self.logic_area_name = name

    def add_location(self, instance_id, bbox, page_number, raw_text: List[str] = None):
        location_item = LocationItem(reference_instance_id=instance_id,
                                     page_number=page_number,
                                     location=LocationTerm(left=bbox[0], top=bbox[1], right=bbox[2], bottom=bbox[3]),
                                     raw_pdf_text_list=raw_text if raw_text else [])
        self.location_list.append(location_item)


class PhysicalPageTerm(StrictModel):
    instance_id: str = Field(..., description="表示属于哪个pdf示例")
    page_number: int = Field(..., description="对应物理页页码，从1开始")


class LogicPageTerm(StrictModel):
    logic_page_id: str = Field(default_factory=lambda: generate_id())
    logic_page_name: str = Field(...)
    logic_page_config: str | dict = Field(default="")
    logic_page_body: List[LogicSectionTerm] = Field(default_factory=list)
    logic_page_relation: List[PhysicalPageTerm] = Field(default_factory=list)


ABContentTerm = Annotated[
    Union[
        SingleMappingTableTerm,
        TwoLevelTableTerm,
        PivotTableTerm,
    ],
    Field(discriminator="tree_node_type")
]

class TreeNodeTerm(StrictModel):
    node_id: str = Field(default_factory=lambda: generate_id(), description="节点唯一ID", json_schema_extra={"x_llm_generated": False})
    xml_name_property: XmlNamePropertyTerm = Field(default_factory=lambda: XmlNamePropertyTerm())
    annotation: Optional[str] = Field("")
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=lambda: EdslSemiStructTerm(), json_schema_extra={"x_llm_generated": False})
    edsl_prompt: EdslPromptTerm = Field(default_factory=lambda: EdslPromptTerm(), json_schema_extra={"x_llm_generated": False})
    tree_node_type: str = Field(...)
    reference_logic_area_id_list: List[str] = Field(default_factory=list)

    # 可选字段（根据 tree_node_type 动态决定）
    support_big_cust_acct: Optional[SupportBigCustAcctTerm] = None
    data_expression: Optional[DataExpressionTerm] = None
    data_type_config: Optional[DataTypeTerm] = None
    children: List['TreeNodeTerm'] = None
    ab_content: Optional[ABContentTerm] = None
    local_context: List[Any] = None
    iter_local_context: List[Any] = None
    data_source: Optional[DataSourceTerm] = None

    class Config:
        special_configs = {
            "parent": {
                'children': list,
                'local_context': list,
            },
            "simple_leaf": {
                'data_expression': DataExpressionTerm,
                'data_type_config': DataTypeTerm,
                'support_big_cust_acct': SupportBigCustAcctTerm,
            },
            "parent_list": {
                'data_source': DataSourceTerm,
                'support_big_cust_acct': SupportBigCustAcctTerm,
                'children': list,
                'local_context': list,
                'iter_local_context': list,
            },
            "ab_single_mapping_table": {
                'ab_content': SingleMappingTableTerm,
            },
            "ab_two_level_table": {
                'ab_content': TwoLevelTableTerm,
            },
            "ab_pivot_table": {
                'ab_content': PivotTableTerm,
            },
        }

        # 定义每个 tree_node_type 允许的字段集合（用于校验修复）
        allowed_fields_per_type: dict = {
            "parent": {"children", "local_context"},
            "simple_leaf": {"data_expression", "data_type_config", "support_big_cust_acct"},
            "parent_list": {"data_source", "support_big_cust_acct", "children", "local_context", "iter_local_context"},
            "ab_single_mapping_table": {"ab_content"},
            "ab_two_level_table": {"ab_content"},
            "ab_pivot_table": {"ab_content"},
        }

        # 基础字段（所有类型都可能有）
        base_fields = {
            "node_id", "xml_name_property", "annotation", "edsl_semi_struct",
            "edsl_prompt", "tree_node_type", "reference_logic_area_id_list"
        }

        # ab表类型集合
        ab_table_type_list = ["ab_pivot_table", "ab_two_level_table", "ab_single_mapping_table"]

    @model_validator(mode="before")
    @classmethod
    def fill_ab_content_type(cls, data: Any):
        if isinstance(data, dict):
            tree_node_type = data.get("tree_node_type")
            ab_content = data.get("ab_content")
            if isinstance(ab_content, dict) and tree_node_type in cls.Config.ab_table_type_list:
                ab_content.setdefault("tree_node_type", tree_node_type)
        return data

    @model_validator(mode='after')
    def adjust_for_node_type(self) -> 'TreeNodeTerm':
        # 获取当前 tree_node_type 允许的字段集合
        allowed_fields = self.Config.base_fields.copy()
        if self.tree_node_type in self.Config.allowed_fields_per_type:
            allowed_fields.update(self.Config.allowed_fields_per_type[self.tree_node_type])

        # 删除不属于该类型的可选字段
        optional_field_names = {
            'data_expression', 'data_type_config', 'children', 'ab_content',
            'local_context', 'iter_local_context', 'data_source', 'support_big_cust_acct'
        }
        for field_name in optional_field_names:
            if field_name not in allowed_fields:
                if hasattr(self, field_name):
                    setattr(self, field_name, None)

        # 填充缺失的属性
        if self.tree_node_type in self.Config.special_configs:
            config = self.Config.special_configs[self.tree_node_type]
            for field_name, value_factory in config.items():
                current_value = getattr(self, field_name, None)
                if current_value is None:
                    setattr(self, field_name, value_factory())

        return self

    def update_id(self):
        self.node_id = generate_id()

    def get_bo_source_in_ab(self):
        bo_name = None
        if self.tree_node_type in self.Config.ab_table_type_list:
            data_source = self.ab_content.data_source
            if data_source.data_source_type == "sql":
                bo_name = data_source.sql_query.bo_name

        return bo_name

    def is_ab_node(self):
        return self.tree_node_type in self.Config.ab_table_type_list


class FontConfigTerm(StrictModel):
    # 假设该结构已定义，这里仅保留占位
    # 示例字段可能包括: name, size, bold, italic 等
    pass


class PdfGlobalConfig(StrictModel):
    page_size: str = Field("A4", description="页面尺寸")
    page_margin: PageMargin = Field(default_factory=lambda: PageMargin(), description="页边距")
    default_font: str | dict = Field("", description="默认字体配置")


class BillContentTerm(StrictModel):
    pdf_global_config: PdfGlobalConfig = Field(default_factory=lambda: PdfGlobalConfig(), description="PDF全局配置")
    instances: List[dict] = Field(
        default_factory=list,
        description="账单实例列表",
        validation_alias=AliasChoices("bill_instances", "pdf_instances"),
        serialization_alias="pdf_instances"
    )
    global_head: List[LogicSectionTerm] = Field(
        default_factory=list, title="全局页眉", description="全局页眉内容，page_number 必须为 -1"
    )
    global_foot: List[LogicSectionTerm] = Field(
        default_factory=list, title="全局页脚", description="全局页脚内容，page_number 必须为 -1"
    )
    logic_pages: List[LogicPageTerm] = Field(default_factory=list, description="逻辑页列表")

    # 兼容属性：允许通过 pdf_instances 访问 bill_instances
    @property
    def pdf_instances(self) -> List[dict]:
        return self.instances

    @pdf_instances.setter
    def pdf_instances(self, value: List[dict]):
        self.instances = value

    def whether_duplicate_pages_exist(self, page_type: str) -> int:
        for index, page in enumerate(self.logic_pages):
            if page.logic_page_name == page_type:
                return index
        return -1


def generate_root_node():
    root_node = TreeNodeTerm(
        xml_name_property=XmlNamePropertyTerm(xml_name="BILL_INFO"),
        annotation="账单信息",
        tree_node_type="parent"
    )
    return root_node


class TimeTypeConfig(StrictModel):
    time_format_expression: str = Field("\"yyyyMMddHHmmss\"")
    region_id_expression: Optional[str] = None


class MoneyTypeConfig(StrictModel):
    int_delimiter_expression: str = Field("','")
    intp_delimiter_expression: str = Field("'.'")
    round_method_expression: str = Field("3")
    currency_unit: str = Field("B")
    decimal_precision: str = Field("2")
    zero_padding: str = Field("Y")
    currency_id_expression: Optional[str] = None


class FlowTypeConfig(StrictModel):
    flow_type_expression: str = None


class ProjectLevelConfig(StrictModel):
    time_type_config: TimeTypeConfig = Field(default_factory=lambda: TimeTypeConfig())
    money_type_config: MoneyTypeConfig = Field(default_factory=lambda: MoneyTypeConfig())
    flow_type_config: Optional[FlowTypeConfig] = None


class DSLProject(StrictModel):
    project_type: str = Field(default="pdf_based_v2")
    project_level_config: ProjectLevelConfig = Field(default_factory=lambda: ProjectLevelConfig())
    mapping_content: Optional[TreeNodeTerm] = None
    bill_content: Optional[BillContentTerm] = Field(
        default=None,
        validation_alias=AliasChoices("bill_content", "pdf_content"),
        serialization_alias="pdf_content"
    )

    # 兼容属性：允许通过 pdf_content 访问 bill_content
    @property
    def pdf_content(self) -> Optional[BillContentTerm]:
        return self.bill_content

    @pdf_content.setter
    def pdf_content(self, value: Optional[BillContentTerm]):
        self.bill_content = value

    @model_validator(mode='after')
    def validate_project_type_constraints(self) -> 'DSLProject':
        p_type = self.project_type

        # 获取当前字段值
        has_mapping = self.mapping_content is not None
        has_pdf = self.bill_content is not None
        has_config = self.project_level_config is not None

        if not has_config:
            raise ValueError("'project_level_config' must be None.")

        if p_type == "xml_based":
            # 2. xml_based: 除了 mapping_content 以外其他都必须为 None
            if has_pdf:
                self.bill_content = None
            if not has_mapping:
                self.mapping_content = generate_root_node()

        elif p_type in ["pdf_based_v2", "excel"]:
            # 4. pdf_based_v2: 必须同时拥有 mapping_content 和 bill_content
            # 注意：需求没说 project_level_config 必须为 None，所以这里只校验必须存在的字段
            if not has_mapping:
                raise ValueError("When project_type is 'pdf_based_v2' or 'excel', 'mapping_content' is required.")
            if not has_pdf:
                raise ValueError("When project_type is 'pdf_based_v2' or 'excel', 'bill_content' is required.")


        return self
