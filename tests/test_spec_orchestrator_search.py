from agent.environment.namingsql_seletor import NamingSqlSelector
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    ContextRegistry,
    DataTypeEnum,
    DomainRegistry,
    FunctionRegistry,
    NamingSqlDefTerm,
    ParamTerm,
    ParamTypeTerm,
    PropertyTerm,
    PropertyTypeEnum,
    ReturnType,
    ReturnTypeTerm,
)
from agent.resource_manager.loader.resource_loader import LoadedResource
from agent.spec_orchestration.models import GoalRole, GoalSearchRequest, ResourceTier, ValueGoal
from agent.spec_orchestration.search import OrchestratorResourceSearch


class FakeEmbeddingClient:
    def __init__(self, vectors_by_text=None, *, failure=None):
        self.vectors_by_text = vectors_by_text or {}
        self.failure = failure
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        if self.failure is not None:
            raise self.failure
        return [self.vectors_by_text[text] for text in texts]


def _loaded_resource():
    return LoadedResource(
        context_registry={
            "$ctx$.invoice.invoiceId": ContextRegistry(
                resource_id="ctx.invoice_id",
                context_name="$ctx$.invoice.invoiceId",
                return_type=ReturnType(data_type="basic", data_type_name="long", is_list=False),
                property_type=PropertyTypeEnum.system,
                annotation="账单发票ID",
                tag=["invoice", "invoiceId"],
            )
        },
        bo_registry={
            "BB_DIC_CUSTGRP": BoRegistry(
                resource_id="bo.custgrp",
                bo_name="BB_DIC_CUSTGRP",
                bo_desc="客户组字典",
                property_list=[
                    PropertyTerm(
                        field_name="CUST_GRP_ID",
                        description="客户组ID",
                        data_type=DataTypeEnum.key,
                        data_type_name="long",
                    ),
                    PropertyTerm(
                        field_name="CUST_GRP_NAME",
                        description="客户组名称",
                        data_type=DataTypeEnum.basic,
                        data_type_name="string",
                    ),
                    PropertyTerm(
                        field_name="REGION_CODE",
                        description="区域编码",
                        data_type=DataTypeEnum.basic,
                        data_type_name="string",
                    ),
                ],
            ),
            "BB_BILL_CUSTGRP": BoRegistry(
                resource_id="bo.bill_custgrp",
                bo_name="BB_BILL_CUSTGRP",
                bo_desc="账单客户组",
                property_list=[
                    PropertyTerm(
                        field_name="CUST_GRP_ID",
                        description="客户组ID",
                        data_type=DataTypeEnum.basic,
                        data_type_name="long",
                    )
                ],
                naming_sql_list=[
                    NamingSqlDefTerm(
                        naming_sql_id="sql.by_invoice",
                        sql_name="E_BB_BILL_CUSTGRP_QUERYBY_INVOICEID",
                        param_list=[
                            ParamTerm(param_name="INVOICE_ID", data_type_name="long")
                        ],
                    )
                ],
            ),
        },
        function_registry={
            "BuildCustGroupName": FunctionRegistry(
                resource_id="fn.cust_group_name",
                func_name="BuildCustGroupName",
                func_desc="生成客户组名称",
                param_list=[
                    ParamTypeTerm(
                        param_name="custGrpId",
                        data_type=DataTypeEnum.basic,
                        data_type_name="long",
                    )
                ],
                return_type=ReturnTypeTerm(
                    data_type=DataTypeEnum.basic,
                    data_type_name="string",
                    is_list=False,
                ),
            )
        },
        edsl_tree={},
        domain_registry=DomainRegistry(),
    )


def _goal(name="客户组名称", type_name="string"):
    return ValueGoal(
        goal_id="root",
        semantic_name=name,
        role=GoalRole.FINAL_OUTPUT,
        expected_type=ReturnType(
            data_type="basic", data_type_name=type_name, is_list=False
        ),
    )


def test_context_search_only_returns_canonical_matching_context():
    loaded = _loaded_resource()
    embedding = FakeEmbeddingClient()
    search = OrchestratorResourceSearch(loaded, embedding_client=embedding)
    request = GoalSearchRequest(
        goal=_goal("账单发票ID", "long"),
        tier=ResourceTier.VISIBLE_VALUE,
        keywords=["invoiceId", "发票ID"],
    )

    candidates = search.search(request)

    assert [item.candidate_id for item in candidates] == ["ctx.invoice_id"]
    assert candidates[0].resource is loaded.context_registry["$ctx$.invoice.invoiceId"]
    assert embedding.calls == []


def test_context_search_matches_canonical_path_suffix_without_embedding():
    loaded = _loaded_resource()
    embedding = FakeEmbeddingClient()
    search = OrchestratorResourceSearch(loaded, embedding_client=embedding)
    request = GoalSearchRequest(
        goal=_goal("发票标识", "long"),
        tier=ResourceTier.VISIBLE_VALUE,
        keywords=["invoice.invoiceId"],
    )

    candidates = search.search(request)

    assert [item.candidate_id for item in candidates] == ["ctx.invoice_id"]
    assert embedding.calls == []


def test_bo_field_search_marks_key_and_returns_matching_field():
    search = OrchestratorResourceSearch(_loaded_resource())
    request = GoalSearchRequest(
        goal=_goal(),
        tier=ResourceTier.BO_FIELD,
        keywords=["CUST_GRP_NAME", "客户组名称"],
    )

    candidates = search.search(request)

    assert [(item.bo_name, item.field_name) for item in candidates] == [
        ("BB_DIC_CUSTGRP", "CUST_GRP_NAME")
    ]
    assert candidates[0].is_key is False


def test_bo_field_semantic_score_uses_best_individual_keyword_and_returns_property():
    loaded = _loaded_resource()
    fields = {
        field.field_name: field
        for bo in loaded.bo_registry.values()
        for field in bo.property_list
    }
    embedding = FakeEmbeddingClient(
        {
            "客户": [1.0, 0.0],
            "显示名称": [0.0, 1.0],
            "业务对象：BB_DIC_CUSTGRP 业务对象含义：客户组字典 字段：CUST_GRP_ID 字段含义：客户组ID 标签：": [0.7, 0.7],
            "业务对象：BB_DIC_CUSTGRP 业务对象含义：客户组字典 字段：CUST_GRP_NAME 字段含义：客户组名称 标签：": [0.0, 1.0],
            "业务对象：BB_DIC_CUSTGRP 业务对象含义：客户组字典 字段：REGION_CODE 字段含义：区域编码 标签：": [-1.0, 0.0],
            "业务对象：BB_BILL_CUSTGRP 业务对象含义：账单客户组 字段：CUST_GRP_ID 字段含义：客户组ID 标签：": [0.7, 0.7],
        }
    )
    search = OrchestratorResourceSearch(loaded, embedding_client=embedding)
    request = GoalSearchRequest(
        goal=_goal("展示值"),
        tier=ResourceTier.BO_FIELD,
        keywords=["客户"],
        aliases=["显示名称"],
        negative_keywords=["区域"],
        limit=2,
    )

    candidates = search.search(request)

    assert candidates[0].field_name == "CUST_GRP_NAME"
    assert candidates[0].metadata["field"] is fields["CUST_GRP_NAME"]
    assert all(item.field_name != "REGION_CODE" for item in candidates)
    assert embedding.calls[0][:2] == ["客户", "显示名称"]


def test_bo_field_reuses_cached_resource_vectors_across_goals():
    loaded = _loaded_resource()
    documents = [
        (
            f"业务对象：{bo.bo_name} 业务对象含义：{bo.bo_desc} "
            f"字段：{field.field_name} 字段含义：{field.description or ''} "
            f"标签：{' '.join(bo.tag)}"
        )
        for bo in loaded.bo_registry.values()
        for field in bo.property_list
    ]
    vectors = {text: [1.0, 0.0] for text in documents}
    vectors.update({"名称": [1.0, 0.0], "编码": [0.0, 1.0]})
    embedding = FakeEmbeddingClient(vectors)
    search = OrchestratorResourceSearch(loaded, embedding_client=embedding)

    search.search(
        GoalSearchRequest(
            goal=_goal("名称"),
            tier=ResourceTier.BO_FIELD,
            keywords=["名称"],
        )
    )
    search.search(
        GoalSearchRequest(
            goal=_goal("编码"),
            tier=ResourceTier.BO_FIELD,
            keywords=["编码"],
        )
    )

    assert embedding.calls[0] == ["名称", *documents]
    assert embedding.calls[1] == ["编码"]


def test_bo_field_embedding_failure_falls_back_to_bounded_lexical_matches():
    embedding = FakeEmbeddingClient(failure=RuntimeError("offline"))
    search = OrchestratorResourceSearch(
        _loaded_resource(),
        embedding_client=embedding,
    )
    request = GoalSearchRequest(
        goal=_goal("客户组名称"),
        tier=ResourceTier.BO_FIELD,
        keywords=["CUST_GRP_NAME"],
        limit=1,
    )

    candidates = search.search(request)

    assert [item.field_name for item in candidates] == ["CUST_GRP_NAME"]


def test_bo_access_search_does_not_mix_relation_with_naming_sql():
    search = OrchestratorResourceSearch(_loaded_resource())
    request = GoalSearchRequest(
        goal=_goal("客户组ID", "long"),
        tier=ResourceTier.BO_ACCESS,
        keywords=["CUST_GRP_ID"],
        target_bo_name="BB_DIC_CUSTGRP",
    )

    candidates = search.search(request)

    assert candidates == []


def test_bo_select_fallback_uses_primary_key_when_query_has_no_condition():
    search = OrchestratorResourceSearch(_loaded_resource())
    request = GoalSearchRequest(
        goal=ValueGoal(
            goal_id="root::__bo__:BB_DIC_CUSTGRP",
            semantic_name="BB_DIC_CUSTGRP",
            role=GoalRole.INTERMEDIATE_VALUE,
            expected_type=ReturnType(
                data_type="bo",
                data_type_name="BB_DIC_CUSTGRP",
                is_list=False,
            ),
            target_bo_name="BB_DIC_CUSTGRP",
            target_field_name="CUST_GRP_NAME",
        ),
        tier=ResourceTier.BO_SELECT,
        keywords=["客户组名称"],
        target_bo_name="BB_DIC_CUSTGRP",
        target_field_name="CUST_GRP_NAME",
        query="获取客户组名称",
    )

    candidates = search.search(request)

    assert len(candidates) == 1
    assert candidates[0].kind == "bo_select"
    assert candidates[0].metadata["operation"] == "select_one"
    assert [item.name for item in candidates[0].required_inputs] == [
        "CUST_GRP_ID"
    ]
    assert candidates[0].required_inputs[0].return_type.data_type == "key"


def test_bo_select_uses_condition_field_explicitly_named_in_query():
    search = OrchestratorResourceSearch(_loaded_resource())
    request = GoalSearchRequest(
        goal=ValueGoal(
            goal_id="root::__bo__:BB_DIC_CUSTGRP",
            semantic_name="BB_DIC_CUSTGRP",
            role=GoalRole.INTERMEDIATE_VALUE,
            expected_type=ReturnType(
                data_type="bo",
                data_type_name="BB_DIC_CUSTGRP",
                is_list=False,
            ),
            target_bo_name="BB_DIC_CUSTGRP",
            target_field_name="CUST_GRP_NAME",
        ),
        tier=ResourceTier.BO_SELECT,
        target_bo_name="BB_DIC_CUSTGRP",
        target_field_name="CUST_GRP_NAME",
        query="根据 REGION_CODE 获取客户组名称",
    )

    candidates = search.search(request)

    assert [item.name for item in candidates[0].required_inputs] == [
        "REGION_CODE"
    ]
    assert candidates[0].evidence == ["query condition field match"]


def test_literal_is_last_resort_for_string_value_goal():
    search = OrchestratorResourceSearch(_loaded_resource())
    request = GoalSearchRequest(
        goal=_goal("固定文本", "string"),
        tier=ResourceTier.LITERAL,
        query="固定填写 已完成",
    )

    candidates = search.search(request)

    assert len(candidates) == 1
    assert candidates[0].kind == "literal"
    assert candidates[0].metadata["value"] == "固定文本"


def test_naming_sql_and_function_candidates_expose_real_inputs():
    loaded = _loaded_resource()
    search = OrchestratorResourceSearch(
        loaded, naming_sql_retriever=NamingSqlSelector()
    )
    sql_request = GoalSearchRequest(
        goal=_goal("账单客户组", "BB_BILL_CUSTGRP"),
        tier=ResourceTier.BO_ACCESS,
        keywords=["invoice", "QUERYBY_INVOICEID"],
        target_bo_name="BB_BILL_CUSTGRP",
    )
    function_request = GoalSearchRequest(
        goal=_goal(),
        tier=ResourceTier.FUNCTION,
        keywords=["BuildCustGroupName", "客户组名称"],
    )

    sql_candidates = search.search(sql_request)
    function_candidates = search.search(function_request)

    sql = next(item for item in sql_candidates if item.kind == "naming_sql")
    assert [item.name for item in sql.required_inputs] == ["INVOICE_ID"]
    assert [item.name for item in function_candidates[0].required_inputs] == [
        "custGrpId"
    ]


def test_function_filters_incompatible_return_type_before_embedding():
    loaded = _loaded_resource()
    loaded.function_registry["BuildCustomerCount"] = FunctionRegistry(
        resource_id="fn.customer_count",
        func_name="BuildCustomerCount",
        func_desc="统计客户数量",
        return_type=ReturnTypeTerm(
            data_type=DataTypeEnum.basic,
            data_type_name="long",
            is_list=False,
        ),
    )
    compatible_text = (
        "函数：BuildCustGroupName 功能：生成客户组名称 类别： 标签： "
        "输入：custGrpId:basic/long 输出：basic/string/False"
    )
    embedding = FakeEmbeddingClient(
        {
            "客户名称": [1.0, 0.0],
            compatible_text: [1.0, 0.0],
        }
    )
    search = OrchestratorResourceSearch(loaded, embedding_client=embedding)
    request = GoalSearchRequest(
        goal=_goal("客户名称", "string"),
        tier=ResourceTier.FUNCTION,
        keywords=["客户名称"],
    )

    candidates = search.search(request)

    assert [item.candidate_id for item in candidates] == ["fn.cust_group_name"]
    assert embedding.calls == [["客户名称", compatible_text]]
