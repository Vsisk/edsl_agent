import agent.spec_orchestration.search as search_module

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


def test_token_cosine_uses_sklearn_pairwise_cosine(monkeypatch):
    calls = []

    def fake_cosine_similarity(left, right):
        calls.append((left, right))
        return [[0.91]]

    monkeypatch.setattr(
        search_module,
        "sklearn_cosine_similarity",
        fake_cosine_similarity,
    )

    similarity = search_module._token_cosine(
        ["cust", "grp", "name"],
        ["cust", "group", "name"],
    )

    assert similarity == 0.91
    assert len(calls) == 1


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


def test_bo_field_matches_property_name_and_never_calls_embedding():
    loaded = _loaded_resource()
    target_field = loaded.bo_registry["BB_DIC_CUSTGRP"].property_list[1]
    embedding = FakeEmbeddingClient(failure=AssertionError("BO must not embed"))
    search = OrchestratorResourceSearch(loaded, embedding_client=embedding)
    request = GoalSearchRequest(
        goal=_goal("展示值"),
        tier=ResourceTier.BO_FIELD,
        keywords=["cust_grp_name"],
        aliases=["CUSTGRPNAME"],
        negative_keywords=["region_code"],
    )

    candidates = search.search(request)

    assert [(item.bo_name, item.field_name) for item in candidates] == [
        ("BB_DIC_CUSTGRP", "CUST_GRP_NAME")
    ]
    assert candidates[0].metadata["field"] is target_field
    assert embedding.calls == []


def test_bo_field_tokenizes_camel_case_and_ranks_by_lexical_cosine():
    loaded = _loaded_resource()
    target_bo = loaded.bo_registry["BB_DIC_CUSTGRP"]
    target_field = PropertyTerm(
        field_name="custGrpName",
        description="",
        data_type=DataTypeEnum.basic,
        data_type_name="string",
    )
    target_bo.property_list.append(target_field)
    embedding = FakeEmbeddingClient(failure=AssertionError("BO must not embed"))
    search = OrchestratorResourceSearch(loaded, embedding_client=embedding)
    request = GoalSearchRequest(
        goal=_goal("展示值"),
        tier=ResourceTier.BO_FIELD,
        keywords=["cust group name"],
    )

    candidates = search.search(request)

    assert ("BB_DIC_CUSTGRP", "custGrpName") in [
        (item.bo_name, item.field_name) for item in candidates
    ]
    candidate = next(item for item in candidates if item.field_name == "custGrpName")
    assert candidate.metadata["field"] is target_field
    assert candidate.metadata["lexical_cosine_similarity"] > 0.8
    assert embedding.calls == []


def test_bo_field_search_processes_bo_registry_in_parallel_batches(monkeypatch):
    loaded = _loaded_resource()
    loaded.bo_registry = {}
    for index in range(5):
        loaded.bo_registry[f"BO_{index}"] = BoRegistry(
            resource_id=f"bo.{index}",
            bo_name=f"BO_{index}",
            bo_desc=f"BO {index}",
            property_list=[
                PropertyTerm(
                    field_name=f"CUST_GRP_NAME_{index}",
                    data_type=DataTypeEnum.basic,
                    data_type_name="string",
                )
            ],
        )
    submitted_batch_sizes = []
    created_workers = []

    class FakeExecutor:
        def __init__(self, max_workers):
            created_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def map(self, fn, batches):
            batch_list = list(batches)
            submitted_batch_sizes.extend(len(batch) for batch in batch_list)
            return [fn(batch) for batch in batch_list]

    monkeypatch.setattr(search_module, "ThreadPoolExecutor", FakeExecutor, raising=False)
    search = OrchestratorResourceSearch(
        loaded,
        bo_search_batch_size=2,
        bo_search_max_workers=3,
    )
    request = GoalSearchRequest(
        goal=_goal("customer group name"),
        tier=ResourceTier.BO_FIELD,
        keywords=["cust group name"],
    )

    candidates = search.search(request)

    assert submitted_batch_sizes == [2, 2, 1]
    assert created_workers == [3]
    assert [item.field_name for item in candidates] == [
        "CUST_GRP_NAME_0",
        "CUST_GRP_NAME_1",
        "CUST_GRP_NAME_2",
        "CUST_GRP_NAME_3",
        "CUST_GRP_NAME_4",
    ]


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
    assert embedding.calls == [["客户名称"], [compatible_text]]


def test_function_resource_embeddings_are_computed_in_bounded_batches():
    loaded = _loaded_resource()
    loaded.function_registry = {}
    documents = []
    vectors = {"格式化": [1.0, 0.0]}
    for index in range(5):
        function = FunctionRegistry(
            resource_id=f"fn.format_{index}",
            func_name=f"FormatValue{index}",
            func_desc=f"格式化值 {index}",
            return_type=ReturnTypeTerm(
                data_type=DataTypeEnum.basic,
                data_type_name="string",
                is_list=False,
            ),
        )
        loaded.function_registry[function.func_name] = function
        document = (
            f"函数：{function.func_name} 功能：{function.func_desc} "
            "类别： 标签： 输入： 输出：basic/string/False"
        )
        documents.append(document)
        vectors[document] = [1.0, float(index)]
    embedding = FakeEmbeddingClient(vectors)
    search = OrchestratorResourceSearch(
        loaded,
        embedding_client=embedding,
        embedding_batch_size=2,
    )

    search.search(
        GoalSearchRequest(
            goal=_goal("格式化结果"),
            tier=ResourceTier.FUNCTION,
            keywords=["格式化"],
        )
    )

    assert embedding.calls == [
        ["格式化"],
        documents[:2],
        documents[2:4],
        documents[4:],
    ]
