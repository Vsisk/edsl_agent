from agent.naming_sql_selector.namingsql_profile_loader import NamingSqlProfile
from agent.naming_sql_selector.namingsql_seletor import NamingSqlSelector
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
