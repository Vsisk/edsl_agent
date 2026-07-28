from agent.resource_manager.loader.namingsql_profile_loader import NamingSqlProfile
from agent.environment.namingsql_seletor import NamingSqlSelector
from agent.environment.environment import filter_resources
from agent.resource_manager.loader.registry_models import FilterTarget, SourceType
from agent.resource_manager.loader.registry_models import DomainRegistry
from agent.resource_manager.loader.resource_loader import LoadedResource

from tests.test_namingsql_profile_loader import _bo


def _profile(name, fields, conditions, optimized):
    return NamingSqlProfile(
        bo_name="OrderBO",
        namingsql_name=name,
        where_conditions=conditions,
        return_fields=fields,
        performance_optimized=optimized,
    )


def test_rule_filter_requires_fields_and_prefers_matching_optimized_condition():
    profiles = [
        _profile("fullScan", ["ORDER_ID", "STATUS"], [], False),
        _profile("byStatus", ["ORDER_ID", "STATUS"], ["STATUS = :status"], False),
        _profile("byId", ["ORDER_ID", "STATUS"], ["ORDER_ID = :id"], True),
        _profile("idOnly", ["ORDER_ID"], ["ORDER_ID = :id"], True),
    ]

    selected = NamingSqlSelector().select(
        query="根据 ORDER_ID 查询订单并返回 ORDER_ID 和 STATUS",
        profiles=profiles,
    )

    assert [item.namingsql_name for item in selected] == ["byId", "byStatus", "fullScan"]


def test_llm_can_choose_only_from_rule_candidates():
    profiles = [
        _profile("byId", ["ORDER_ID", "STATUS"], ["ORDER_ID = :id"], True),
        _profile("fullScan", ["ORDER_ID", "STATUS"], [], False),
    ]

    def choose(query, candidates):
        assert [item.namingsql_name for item in candidates] == ["byId", "fullScan"]
        return ["invented", "fullScan", "byId"]

    selected = NamingSqlSelector(llm_selector=choose).select(
        query="返回 ORDER_ID 和 STATUS",
        profiles=profiles,
    )

    assert [item.namingsql_name for item in selected] == ["fullScan", "byId"]


def test_standard_generate_by_llm_uses_prompt_template(monkeypatch):
    profiles = [
        _profile("byId", ["ORDER_ID"], ["ORDER_ID = :id"], True),
    ]
    calls = []

    class Client:
        is_usable = True

    def generate_by_llm(**kwargs):
        calls.append(kwargs)
        return {"namingsql_names": ["byId"]}

    monkeypatch.setattr(
        "agent.environment.namingsql_seletor.generate_by_llm",
        generate_by_llm,
    )

    selected = NamingSqlSelector(client=Client()).select(
        query="根据 ORDER_ID 查询",
        profiles=profiles,
    )

    assert [item.namingsql_name for item in selected] == ["byId"]
    assert calls == [{
        "prompt_template": "namingsql_selector",
        "llm_name": "base",
        "lang": "zh",
        "client": calls[0]["client"],
        "query": "根据 ORDER_ID 查询",
        "candidates_json": '[{"bo_name":"OrderBO","namingsql_name":"byId","where_conditions":["ORDER_ID = :id"],"return_fields":["ORDER_ID"],"performance_optimized":true}]',
    }]


def test_filter_environment_owns_namingsql_selection():
    bo = _bo("SELECT ORDER_ID, STATUS FROM ORDERS WHERE ORDER_ID = :id")
    loaded_resource = LoadedResource(
        context_registry={},
        bo_registry={"OrderBO": bo},
        function_registry={},
        edsl_tree={},
        domain_registry=DomainRegistry(),
    )

    environment = filter_resources(
        targets=[
            FilterTarget(
                source_type=SourceType.NAMING_SQL,
                domain="OrderBO",
                source_name="findOrder",
            )
        ],
        loaded_resource=loaded_resource,
        resource_limits={"namingsql_count": 5},
        query="根据 ORDER_ID 返回 STATUS",
        select_namingsql=True,
    )

    assert [item.namingsql_name for item in environment.naming_sql_selection] == ["findOrder"]
    assert [item.sql_name for item in environment.selected_bos[0].naming_sql_list] == ["findOrder"]
