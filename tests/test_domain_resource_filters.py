import unittest

from agent.environment.environment import filter_resources
from agent.environment.resource_filter import BOFilter, ContextFilter, FunctionFilter, NamingSQLFilter
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    DataTypeEnum,
    DomainRegistry,
    FilterTarget,
    FunctionRegistry,
    NamingSqlDefTerm,
    ParamTerm,
    ParamTypeTerm,
    PropertyTerm,
    ReturnType,
    ReturnTypeTerm,
    SourceType,
)
from agent.resource_manager.loader.resource_loader import LoadedResource
from tests.test_environment import sample_edsl_tree_payload


def _return_type(name="STRING"):
    return ReturnType(data_type="basic", data_type_name=name, is_list=False)


class DomainResourceFiltersTest(unittest.TestCase):
    def test_context_filter_keeps_exact_matches_across_domains_without_top_k_truncation(self):
        registry = {
            "$ctx$.billStatement.flowType": _context("ctx.0000", "$ctx$.billStatement.flowType"),
            "$ctx$.billStatement.currentBillRun": _context("ctx.0001", "$ctx$.billStatement.currentBillRun"),
            "$ctx$.billStatement.chargeClose": _context("ctx.0002", "$ctx$.billStatement.chargeClose"),
            "$ctx$.curBbBillBalance.chargeClose": _context("ctx.0003", "$ctx$.curBbBillBalance.chargeClose"),
            "$ctx$.other.chargeClose": _context("ctx.0004", "$ctx$.other.chargeClose"),
        }
        targets = [
            FilterTarget(SourceType.CONTEXT, "billStatement", "flowType"),
            FilterTarget(SourceType.CONTEXT, "billStatement", "currentBillRun"),
            FilterTarget(SourceType.CONTEXT, "billStatement", "chargeClose"),
            FilterTarget(SourceType.CONTEXT, "curBbBillBalance", "chargeClose"),
        ]

        result = ContextFilter().filter(targets, registry, top_k=1)

        self.assertEqual(
            [item.context_name for item in result],
            [
                "$ctx$.billStatement.flowType",
                "$ctx$.billStatement.currentBillRun",
                "$ctx$.billStatement.chargeClose",
                "$ctx$.curBbBillBalance.chargeClose",
            ],
        )

    def test_bo_filter_returns_only_target_bo_with_matched_property(self):
        registry = {
            "BB_PREP_SUB": _bo("bo.0000", "BB_PREP_SUB", ["BILL_CYCLE_ID", "OTHER_ID"]),
            "OTHER_BO": _bo("bo.0001", "OTHER_BO", ["BILL_CYCLE_ID"]),
        }

        result = BOFilter().filter(
            [FilterTarget(SourceType.BO, "BB_PREP_SUB", "BILL_CYCLE_ID")],
            registry,
            top_k=1,
        )

        self.assertEqual([bo.bo_name for bo in result], ["BB_PREP_SUB"])
        self.assertEqual([item.field_name for item in result[0].property_list], ["BILL_CYCLE_ID"])

    def test_namingsql_filter_returns_bo_with_matching_namingsql(self):
        bo = _bo("bo.0000", "BB_PREP_SUB", ["PREPARE_ID"])
        bo.naming_sql_list = [
            NamingSqlDefTerm(
                naming_sql_id="sql.1",
                sql_name="QUERY_BY_PREPARE_ID",
                sql_description="query by prepare id",
                param_list=[ParamTerm(param_name="PREPARE_ID", data_type_name="long")],
            ),
            NamingSqlDefTerm(
                naming_sql_id="sql.2",
                sql_name="QUERY_ALL",
                sql_description="query all",
                param_list=[],
            ),
        ]

        result = NamingSQLFilter().filter(
            [FilterTarget(SourceType.NAMING_SQL, "BB_PREP_SUB", "QUERY_BY_PREPARE_ID")],
            {"BB_PREP_SUB": bo},
            top_k=1,
        )

        self.assertEqual([item.bo_name for item in result], ["BB_PREP_SUB"])
        self.assertEqual([item.sql_name for item in result[0].naming_sql_list], ["QUERY_BY_PREPARE_ID"])

    def test_function_filter_dedupes_by_class_and_function_name(self):
        registry = {
            "func.1": _function("func.1", "DateUtils", "formatDate"),
            "func.2": _function("func.2", "DateUtils", "parseDate"),
            "func.3": _function("func.3", "OtherUtils", "formatDate"),
        }

        result = FunctionFilter().filter(
            [
                FilterTarget(SourceType.FUNCTION, "DateUtils", "formatDate"),
                FilterTarget(SourceType.FUNCTION, "DateUtils", "format_date"),
            ],
            registry,
            top_k=1,
        )

        self.assertEqual([(item.func_class, item.func_name) for item in result], [("DateUtils", "formatDate")])

    def test_filter_resources_merges_four_resource_groups(self):
        bo = _bo("bo.0000", "BB_PREP_SUB", ["BILL_CYCLE_ID"])
        bo.naming_sql_list = [
            NamingSqlDefTerm(
                naming_sql_id="sql.1",
                sql_name="QUERY_BY_PREPARE_ID",
                sql_description="query by prepare id",
                param_list=[],
            )
        ]
        loaded = LoadedResource(
            context_registry={"$ctx$.billStatement.flowType": _context("ctx.0000", "$ctx$.billStatement.flowType")},
            bo_registry={"BB_PREP_SUB": bo},
            function_registry={"formatDate": _function("func.1", "DateUtils", "formatDate")},
            edsl_tree=sample_edsl_tree_payload(),
            domain_registry=DomainRegistry(
                ctx_domains=["billStatement"],
                bo_domains=["BB_PREP_SUB"],
                func_domains=["DateUtils"],
                namingsql_domains=["BB_PREP_SUB"],
            ),
        )

        env = filter_resources(
            targets=[
                FilterTarget(SourceType.CONTEXT, "billStatement", "flowType"),
                FilterTarget(SourceType.BO, "BB_PREP_SUB", "BILL_CYCLE_ID"),
                FilterTarget(SourceType.FUNCTION, "DateUtils", "formatDate"),
                FilterTarget(SourceType.NAMING_SQL, "BB_PREP_SUB", "QUERY_BY_PREPARE_ID"),
            ],
            loaded_resource=loaded,
            resource_limits={"context_count": 1, "bo_count": 1, "function_count": 1, "namingsql_count": 1},
        )

        self.assertEqual(env.selected_global_context_ids, ["ctx.0000"])
        self.assertEqual(env.selected_bo_ids, ["bo.0000"])
        self.assertEqual(env.selected_function_ids, ["func.1"])
        self.assertEqual(env.selected_bos[0].property_list[0].field_name, "BILL_CYCLE_ID")
        self.assertEqual(env.selected_bos[0].naming_sql_list[0].sql_name, "QUERY_BY_PREPARE_ID")
        self.assertTrue(env.selection_trace)


def _context(resource_id, context_name):
    from agent.resource_manager.loader.registry_models import ContextRegistry, PropertyTypeEnum

    return ContextRegistry(
        resource_id=resource_id,
        context_name=context_name,
        return_type=_return_type(),
        property_type=PropertyTypeEnum.system,
        annotation=context_name,
    )


def _bo(resource_id, bo_name, fields):
    return BoRegistry(
        resource_id=resource_id,
        bo_name=bo_name,
        bo_desc=f"{bo_name} desc",
        property_list=[
            PropertyTerm(
                field_name=field,
                description=f"{field} desc",
                data_type=DataTypeEnum.basic,
                data_type_name="STRING",
            )
            for field in fields
        ],
    )


def _function(resource_id, func_class, func_name):
    return FunctionRegistry(
        resource_id=resource_id,
        func_name=func_name,
        func_desc=f"{func_name} desc",
        func_class=func_class,
        param_list=[ParamTypeTerm(data_type=DataTypeEnum.basic, data_type_name="STRING", param_name="value")],
        return_type=ReturnTypeTerm(data_type=DataTypeEnum.basic, data_type_name="STRING"),
    )


if __name__ == "__main__":
    unittest.main()
