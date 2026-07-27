from agent.naming_sql_selector.retrieval import NamingSqlCandidateRetriever
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
    search = OrchestratorResourceSearch(loaded)
    request = GoalSearchRequest(
        goal=_goal("账单发票ID", "long"),
        tier=ResourceTier.VISIBLE_VALUE,
        keywords=["invoiceId", "发票ID"],
    )

    candidates = search.search(request)

    assert [item.candidate_id for item in candidates] == ["ctx.invoice_id"]
    assert candidates[0].resource is loaded.context_registry["$ctx$.invoice.invoiceId"]


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


def test_relation_search_uses_key_name_and_type_compatibility():
    search = OrchestratorResourceSearch(_loaded_resource())
    request = GoalSearchRequest(
        goal=_goal("客户组ID", "long"),
        tier=ResourceTier.BO_ACCESS,
        keywords=["CUST_GRP_ID"],
        target_bo_name="BB_DIC_CUSTGRP",
    )

    candidates = search.search(request)

    relation = next(item for item in candidates if item.kind == "relation")
    assert relation.bo_name == "BB_BILL_CUSTGRP"
    assert relation.field_name == "CUST_GRP_ID"
    assert relation.metadata["target_key_field"] == "CUST_GRP_ID"


def test_naming_sql_and_function_candidates_expose_real_inputs():
    loaded = _loaded_resource()
    search = OrchestratorResourceSearch(
        loaded, naming_sql_retriever=NamingSqlCandidateRetriever()
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
