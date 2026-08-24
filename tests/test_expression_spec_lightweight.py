import asyncio
import time

import pytest

from agent.expression_spec import (
    ExpressionSpecGenerator,
    ExpressionSpecWorkflow,
    LogicRequirement,
    MissingRequirement,
    ResourceSearchService,
    SearchRequest,
    SearchRequestGenerator,
    SearchResult,
    SpecDraft,
    SpecGenerationError,
    TargetSpec,
)


def _draft():
    return SpecDraft(
        target=TargetSpec(
            concept_name="account bill id",
            concept_type="identifier",
            scope="sub",
            cardinality="list",
        ),
        logic_requirements=[
            LogicRequirement(
                requirement_id="r1",
                type="value_source",
                semantic="query base account records",
            )
        ],
        known_values={
            "BILL_CYCLE_ID": "bill_cycle_id",
            "PREPARE_ID": "prepare_id",
        },
    )


def test_search_request_uses_independent_constraints_default():
    first = SearchRequest(
        request_id="s1",
        requirement_id="r1",
        resource_types=["context"],
        keywords=["billCycleId"],
        semantic="current bill cycle id",
    )
    second = SearchRequest(
        request_id="s2",
        requirement_id="r1",
        resource_types=["function"],
        keywords=["config"],
        semantic="deduplicate config",
    )

    first.constraints["expected"] = "BC_ACCT"

    assert second.constraints == {}


def test_followup_missing_requirement_becomes_standard_search_request():
    generator = SearchRequestGenerator()

    requests = generator.generate_followup(
        missing_requirements=[
            MissingRequirement(
                requirement_id="r1",
                semantic="current account object",
                resource_types=["context"],
                expected_return_type="BC_ACCT",
                scope="acct",
                introduced_by={"resource": "getAccountAttribute", "param": "acct"},
            )
        ],
        search_results=[],
        context={},
    )

    assert len(requests) == 1
    assert requests[0].resource_types == ["context"]
    assert requests[0].expected_return_type == "BC_ACCT"
    assert requests[0].scope == "acct"
    assert requests[0].introduced_by == {
        "resource": "getAccountAttribute",
        "param": "acct",
    }
    assert "current" in requests[0].keywords
    assert "acct" in requests[0].keywords


def test_resource_search_batch_runs_independent_requests_concurrently():
    async def run():
        started = []

        async def context_search(request):
            started.append((request.request_id, time.perf_counter()))
            await asyncio.sleep(0.05)
            return {
                "resource_type": "context",
                "resource_id": f"$ctx$.{request.request_id}",
            }

        service = ResourceSearchService(searchers={"context": context_search})
        requests = [
            SearchRequest(
                request_id=f"s{index}",
                requirement_id="r1",
                resource_types=["context"],
                keywords=[f"k{index}"],
                semantic=f"semantic {index}",
            )
            for index in range(3)
        ]

        before = time.perf_counter()
        results = await service.search_batch(requests)
        elapsed = time.perf_counter() - before

        assert [item.success for item in results] == [True, True, True]
        assert [item.selected_resource["resource_id"] for item in results] == [
            "$ctx$.s0",
            "$ctx$.s1",
            "$ctx$.s2",
        ]
        assert elapsed < 0.12

    asyncio.run(run())


def test_spec_generator_reports_missing_params_and_then_reuses_resolved_values():
    generator = ExpressionSpecGenerator()
    request = SearchRequest(
        request_id="base_sql",
        requirement_id="r1",
        resource_types=["naming_sql"],
        keywords=["base account"],
        semantic="query base account records",
    )
    result = SearchResult(
        request_id="base_sql",
        success=True,
        selected_resource={
            "resource_type": "naming_sql",
            "resource_id": "QUERY_BB_PREP_SUB_FOR_SUBINFO",
            "params": [
                {"name": "BILL_CYCLE_ID", "data_type": "String"},
                {"name": "PREPARE_ID", "data_type": "String"},
            ],
            "return_type": {"type": "bo", "name": "BB_PREP_SUB", "is_list": True},
        },
    )
    unresolved_draft = _draft().model_copy(update={"known_values": {}})

    open_result = generator.generate(
        query="query account bill ids",
        node={},
        draft=unresolved_draft,
        search_requests=[request],
        search_results=[result],
        context={},
    )

    assert open_result.closed is False
    assert [item.semantic for item in open_result.missing_requirements] == [
        "BILL_CYCLE_ID",
        "PREPARE_ID",
    ]

    closed_result = generator.generate(
        query="query account bill ids",
        node={},
        draft=_draft(),
        search_requests=[request],
        search_results=[result],
        context={},
    )

    assert closed_result.closed is True
    assert closed_result.spec.resources["base_sql"].params == {
        "BILL_CYCLE_ID": "bill_cycle_id",
        "PREPARE_ID": "prepare_id",
    }
    assert closed_result.resolved_values["bill_cycle_id"] == "bill_cycle_id"
    assert closed_result.resolved_values["prepare_id"] == "prepare_id"


def test_workflow_runs_followup_round_until_spec_closes():
    draft = SpecDraft(
        target=TargetSpec(
            concept_name="account attribute",
            scope="acct",
            cardinality="single",
        ),
        logic_requirements=[
            LogicRequirement(
                requirement_id="r1",
                type="value_source",
                semantic="get account attribute",
            )
        ],
        known_values={"attrName": "XXX"},
    )
    initial_request = SearchRequest(
        request_id="fn_account_attr",
        requirement_id="r1",
        resource_types=["function"],
        keywords=["account attribute"],
        semantic="get account attribute",
    )

    class ContextManager:
        def get_context(self, **_):
            return {}

    generator = SearchRequestGenerator(
        initial_builder=lambda **_: (draft, [initial_request])
    )

    async def function_search(_):
        return {
            "resource_type": "function",
            "resource_id": "getAccountAttribute",
            "params": [
                {"name": "acct", "data_type": "BC_ACCT"},
                {"name": "attrName", "data_type": "String"},
            ],
            "return_type": "String",
        }

    async def context_search(_):
        return {
            "resource_type": "context",
            "resource_id": "$ctx$.account",
            "return_type": "BC_ACCT",
        }

    workflow = ExpressionSpecWorkflow(
        context_manager=ContextManager(),
        search_request_generator=generator,
        resource_search_service=ResourceSearchService(
            searchers={
                "function": function_search,
                "context": context_search,
            }
        ),
        expression_spec_generator=ExpressionSpecGenerator(),
    )

    spec = asyncio.run(
        workflow.generate_spec(
            query="get account attribute XXX",
            node={},
            node_path="root/account",
            bill_type="acct",
        )
    )

    assert spec.resources["fn_account_attr"].resource_id == "getAccountAttribute"
    assert spec.resources["fn_account_attr"].params == {
        "acct": "$ctx$.account",
        "attrName": "XXX",
    }


def test_workflow_raises_when_missing_dependency_cannot_be_resolved():
    draft = _draft().model_copy(update={"known_values": {}})
    initial_request = SearchRequest(
        request_id="base_sql",
        requirement_id="r1",
        resource_types=["naming_sql"],
        keywords=["base account"],
        semantic="query base account records",
    )

    class ContextManager:
        def get_context(self, **_):
            return {}

    async def sql_search(_):
        return {
            "resource_type": "naming_sql",
            "resource_id": "QUERY_BB_PREP_SUB_FOR_SUBINFO",
            "params": [{"name": "BILL_CYCLE_ID", "data_type": "String"}],
        }

    async def empty_search(_):
        return None

    workflow = ExpressionSpecWorkflow(
        context_manager=ContextManager(),
        search_request_generator=SearchRequestGenerator(
            initial_builder=lambda **_: (draft, [initial_request])
        ),
        resource_search_service=ResourceSearchService(
            searchers={"naming_sql": sql_search, "context": empty_search}
        ),
        expression_spec_generator=ExpressionSpecGenerator(),
        max_rounds=2,
    )

    with pytest.raises(SpecGenerationError):
        asyncio.run(
            workflow.generate_spec(
                query="query account bill ids",
                node={},
                node_path="root",
                bill_type="sub",
            )
        )
