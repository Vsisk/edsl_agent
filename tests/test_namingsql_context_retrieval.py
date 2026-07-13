from copy import deepcopy

import pytest

from agent.context_manager.errors import ContextBuildError
from agent.naming_sql_selector.context_adapter import NamingSqlSelectionContext
from agent.naming_sql_selector.retrieval import NamingSqlCandidateRetriever
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    DataTypeEnum,
    DomainRegistry,
    NamingSqlDefTerm,
    ParamTerm,
    PropertyTerm,
)
from agent.resource_manager.loader.resource_loader import LoadedResource


def _loaded():
    customer = BoRegistry(
        resource_id="bo.customer", bo_name="Customer", bo_desc="customer records",
        property_list=[PropertyTerm(field_name="CUSTOMER_ID", data_type=DataTypeEnum.basic,
                                    data_type_name="STRING")],
        naming_sql_list=[
            NamingSqlDefTerm(naming_sql_id="by-id", sql_name="FindCustomerById",
                             sql_description="find customer by customer id",
                             param_list=[ParamTerm(param_name="CUSTOMER_ID", data_type_name="STRING")]),
            NamingSqlDefTerm(naming_sql_id="all", sql_name="FindAllCustomers",
                             sql_description="list every customer", param_list=[]),
        ],
    )
    fee = BoRegistry(
        resource_id="bo.fee", bo_name="Fee", bo_desc="fee records", property_list=[],
        naming_sql_list=[NamingSqlDefTerm(
            naming_sql_id="fee-by-customer", sql_name="FindFeesByCustomer",
            sql_description="find fees for customer", param_list=[],
        )],
    )
    return LoadedResource(context_registry={}, bo_registry={"Customer": customer, "Fee": fee},
                          function_registry={}, edsl_tree={}, domain_registry=DomainRegistry())


def _context():
    return NamingSqlSelectionContext(
        query_terms=["find", "customer", "id"],
        authoritative_facts=[{"summary": "CUSTOMER_ID field", "facts": {}}],
        normative_rules=[{"summary": "look up customer by id", "facts": {}}],
    )


def test_exact_bo_and_context_overlap_produce_stable_canonical_top_k():
    loaded = _loaded()
    snapshot = deepcopy(loaded)
    result = NamingSqlCandidateRetriever().retrieve(
        query="FindCustomerById", context=_context(), loaded_resource=loaded,
        target_bo_name="Customer", top_k=2,
    )
    assert [item.naming_sql_id for item in result.candidates] == ["by-id", "all"]
    assert [item.rank for item in result.candidates] == [1, 2]
    assert all(item.source == "resource_registry" for item in result.candidates)
    assert loaded == snapshot


def test_explicit_bo_constraint_is_applied_before_relevance():
    result = NamingSqlCandidateRetriever().retrieve(
        query="fees customer", context=_context(), loaded_resource=_loaded(),
        target_bo_name="Fee", top_k=5,
    )
    assert [item.bo_name for item in result.candidates] == ["Fee"]


def test_unknown_bo_has_stable_no_candidate_error():
    with pytest.raises(ContextBuildError) as raised:
        NamingSqlCandidateRetriever().retrieve(
            query="customer", context=_context(), loaded_resource=_loaded(),
            target_bo_name="Missing", top_k=5,
        )
    assert raised.value.code == "NO_NAMING_SQL_CANDIDATES"


def test_hybrid_results_are_canonicalized_and_cannot_invent_assets():
    class Hybrid:
        def retrieve(self, query, assets, semantic_limit):
            invented = assets[0].model_copy(update={"asset_id": "naming_sql:Invented:x"})
            return [invented]

    with pytest.raises(ContextBuildError) as raised:
        NamingSqlCandidateRetriever(hybrid_retriever=Hybrid()).retrieve(
            query="customer", context=_context(), loaded_resource=_loaded(), top_k=5,
        )
    assert raised.value.code == "INVALID_LLM_OUTPUT"
