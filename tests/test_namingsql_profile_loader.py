from agent.naming_sql_selector.namingsql_profile_loader import NamingSqlProfileLoader
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    DataTypeEnum,
    NamingSqlDefTerm,
    PropertyTerm,
)


def _bo(sql: str) -> BoRegistry:
    return BoRegistry(
        resource_id="bo.orders",
        bo_name="OrderBO",
        bo_desc="orders",
        property_list=[
            PropertyTerm(
                field_name="ORDER_ID",
                data_type=DataTypeEnum.key,
                data_type_name="long",
            ),
            PropertyTerm(
                field_name="STATUS",
                data_type=DataTypeEnum.basic,
                data_type_name="String",
            ),
        ],
        naming_sql_list=[
            NamingSqlDefTerm(
                naming_sql_id="sql-1",
                sql_name="findOrder",
                sql_command=sql,
                param_list=[],
            )
        ],
    )


def test_loader_extracts_only_selection_profile_facts():
    profile = NamingSqlProfileLoader().load_bo(
        _bo("SELECT ORDER_ID, STATUS FROM ORDERS WHERE ORDER_ID = :id")
    )[0]

    assert profile.model_dump() == {
        "bo_name": "OrderBO",
        "namingsql_name": "findOrder",
        "where_conditions": ["ORDER_ID = :id"],
        "return_fields": ["ORDER_ID", "STATUS"],
        "performance_optimized": True,
    }


def test_loader_marks_full_scan_as_not_optimized():
    profile = NamingSqlProfileLoader().load_bo(
        _bo("SELECT ORDER_ID FROM ORDERS WHERE 1=1")
    )[0]

    assert profile.where_conditions == []
    assert profile.performance_optimized is False
