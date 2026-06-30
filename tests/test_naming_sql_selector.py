import unittest

from pydantic import ValidationError

from agent.naming_sql_selector import (
    AvailableValue,
    BoCandidate,
    BoResolver,
    DataAccessSpec,
    DataAccessSpecGenerator,
    DevelopmentKnowledge,
    NamingSqlSelectionRequest,
    StaticDevelopmentKnowledgeRetriever,
    NamingSqlProfile,
    NamingSqlParamProfile,
    NamingSqlSelector,
    NamingSqlSelectionResult,
    LocalNamingSqlCandidateRetriever,
    ParamBindingPlan,
)
from agent.resource_manager.loader.resource_loader import LoadedResource
from agent.resource_manager.loader.registry_models import DomainRegistry
from agent.resource_manager.models import BoRegistry, DataTypeEnum, PropertyTerm
from agent.naming_sql_selector.spec_generator import (
    MAX_AVAILABLE_CONTEXT,
    MAX_COMBINED_QUERY_CHARS,
    MAX_MERGED_TERMS,
    MAX_TERM_CHARS,
)


class DataAccessSpecGeneratorTests(unittest.TestCase):
    def test_structured_true_merges_context_and_knowledge(self):
        retriever = StaticDevelopmentKnowledgeRetriever(
            {
                "site-a": [
                    DevelopmentKnowledge(
                        text="account transaction lookup",
                        bo_names=["BO_AR_TRANS"],
                        semantic_tags=["account"],
                    )
                ]
            }
        )
        request = NamingSqlSelectionRequest(
            site_id="site-a",
            query="account transaction",
            structured_spec={"requires_naming_sql": True, "scope_terms": ["account"]},
            available_context=[
                {"name": "Amount", "source_ref": "orders.account.amount", "data_type": "decimal"}
            ],
        )

        spec = DataAccessSpecGenerator(retriever).generate(request)

        self.assertTrue(spec.requires_naming_sql)
        self.assertIn("BO_AR_TRANS", spec.bo_hints)
        self.assertIn("account", spec.scope_terms)
        self.assertEqual("orders.account.amount", spec.available_values[0].source_ref)

    def test_explicit_false_overrides_lookup_language(self):
        request = NamingSqlSelectionRequest(
            site_id="site-a", query="请查询表 account", structured_spec={"requires_naming_sql": False}
        )
        self.assertFalse(DataAccessSpecGenerator().generate(request).requires_naming_sql)

    def test_missing_flag_infers_only_specific_lookup_terms(self):
        generator = DataAccessSpecGenerator()
        for phrase in ("查表", "查询表", "datasource", "data source", "naming sql", "namingsql"):
            with self.subTest(phrase=phrase):
                request = NamingSqlSelectionRequest(site_id="s", query=f"please {phrase} now")
                self.assertTrue(generator.generate(request).requires_naming_sql)
        self.assertFalse(generator.generate(NamingSqlSelectionRequest(site_id="s", query="query account totals")).requires_naming_sql)

    def test_inference_terms_do_not_match_inside_larger_identifiers(self):
        generator = DataAccessSpecGenerator()
        for phrase in ("mydatasourcehelper", "renamingsqltable"):
            with self.subTest(phrase=phrase):
                request = NamingSqlSelectionRequest(site_id="s", query=phrase)
                self.assertFalse(generator.generate(request).requires_naming_sql)

    def test_copies_filter_requirements_and_allow_full_table(self):
        request = NamingSqlSelectionRequest(
            site_id="s",
            query="ordinary",
            structured_spec={"filter_requirements": ["year = 2025"], "allow_full_table": True},
        )
        spec = DataAccessSpecGenerator().generate(request)
        self.assertEqual(["year = 2025"], spec.filter_requirements)
        self.assertTrue(spec.allow_full_table)

    def test_context_derives_and_deduplicates_semantic_tags(self):
        request = NamingSqlSelectionRequest(
            site_id="s",
            query="ordinary",
            available_context=[{
                "name": "Account Amount",
                "source_ref": "AR/account_amount",
                "semantic_tags": ["account", "account", 3],
            }],
        )
        value = DataAccessSpecGenerator().generate(request).available_values[0]
        self.assertEqual(len(value.semantic_tags), len(set(value.semantic_tags)))
        self.assertIn("account", value.semantic_tags)
        self.assertIn("amount", value.semantic_tags)
        self.assertIn("ar", value.semantic_tags)

    def test_knowledge_failure_is_nonfatal(self):
        class FailingRetriever:
            def retrieve(self, site_id, query, limit=5):
                raise RuntimeError("unavailable")

        request = NamingSqlSelectionRequest(site_id="s", query="查表")
        self.assertTrue(DataAccessSpecGenerator(FailingRetriever()).generate(request).requires_naming_sql)

    def test_generator_ignores_malformed_knowledge_and_merges_at_most_five(self):
        class UnboundedRetriever:
            def retrieve(self, site_id, query, limit=5):
                return [
                    None,
                    {"text": "one", "bo_names": ["BO_1"]},
                    {"wrong": "shape"},
                    *[
                        DevelopmentKnowledge(text=str(number), bo_names=[f"BO_{number}"])
                        for number in range(2, 8)
                    ],
                ]

        spec = DataAccessSpecGenerator(UnboundedRetriever()).generate(
            NamingSqlSelectionRequest(site_id="s", query="ordinary")
        )
        self.assertEqual(["BO_1", "BO_2", "BO_3", "BO_4", "BO_5"], spec.bo_hints)

    def test_structured_business_term_participates_in_retrieval(self):
        retriever = StaticDevelopmentKnowledgeRetriever({
            "s": [DevelopmentKnowledge(text="fee schedule", bo_names=["BO_FEE"])]
        })
        request = NamingSqlSelectionRequest(
            site_id="s", query="ordinary", structured_spec={"business_terms": ["fee"]}
        )
        self.assertIn("BO_FEE", DataAccessSpecGenerator(retriever).generate(request).bo_hints)

    def test_bounds_and_normalizes_request_and_knowledge_data(self):
        class CapturingRetriever:
            query = ""

            def retrieve(self, site_id, query, limit=5):
                self.query = query
                return [DevelopmentKnowledge(
                    text="knowledge",
                    bo_names=[f"  BO_{index}\n detail  " for index in range(60)],
                    semantic_tags=[f"  tag {index}\n value  " + ("x" * 200) for index in range(60)],
                )]

        retriever = CapturingRetriever()
        request = NamingSqlSelectionRequest(
            site_id="s",
            query="q" * 5000,
            node={"payload": "n" * 5000},
            structured_spec={"bo_hints": [f"REQ_{index}" for index in range(60)]},
            available_context=[{"name": f"value {index}", "source_ref": f"path/{index}"} for index in range(120)],
        )
        spec = DataAccessSpecGenerator(retriever).generate(request)

        self.assertLessEqual(len(retriever.query), MAX_COMBINED_QUERY_CHARS)
        self.assertEqual(MAX_MERGED_TERMS, len(spec.bo_hints))
        self.assertLessEqual(len(spec.business_terms), MAX_MERGED_TERMS)
        self.assertTrue(all("\n" not in value and len(value) <= MAX_TERM_CHARS for value in spec.business_terms))
        self.assertEqual(MAX_AVAILABLE_CONTEXT, len(spec.available_values))

    def test_circular_node_is_nonfatal_and_query_is_still_retrieved(self):
        class CapturingRetriever:
            query = ""

            def retrieve(self, site_id, query, limit=5):
                self.query = query
                return []

        circular = {}
        circular["self"] = circular
        retriever = CapturingRetriever()
        request = NamingSqlSelectionRequest(site_id="s", query="fee", node=circular)

        spec = DataAccessSpecGenerator(retriever).generate(request)

        self.assertFalse(spec.requires_naming_sql)
        self.assertIn("fee", retriever.query)

    def test_node_annotation_alone_triggers_lookup_inference(self):
        request = NamingSqlSelectionRequest(site_id="s", query="ordinary", node={"annotation": "请查表"})
        self.assertTrue(DataAccessSpecGenerator().generate(request).requires_naming_sql)

    def test_parent_annotation_alone_triggers_lookup_inference(self):
        request = NamingSqlSelectionRequest(
            site_id="s", query="ordinary", parent_node={"annotation": "use data source"}
        )
        self.assertTrue(DataAccessSpecGenerator().generate(request).requires_naming_sql)

    def test_raw_nonstandard_structured_content_participates_in_retrieval(self):
        class CapturingRetriever:
            query = ""

            def retrieve(self, site_id, query, limit=5):
                self.query = query
                return []

        retriever = CapturingRetriever()
        request = NamingSqlSelectionRequest(
            site_id="s", query="ordinary", structured_spec={"domain_annotation": "special-fee-context"}
        )
        DataAccessSpecGenerator(retriever).generate(request)
        self.assertIn("special-fee-context", retriever.query)


class StaticDevelopmentKnowledgeRetrieverTests(unittest.TestCase):
    def test_relevance_site_isolation_limit_and_deterministic_order(self):
        entries = [
            DevelopmentKnowledge(text="account alpha", bo_names=["first"]),
            DevelopmentKnowledge(text="account beta", bo_names=["second"]),
            DevelopmentKnowledge(text="unrelated"),
        ]
        retriever = StaticDevelopmentKnowledgeRetriever({"a": entries, "b": [DevelopmentKnowledge(text="account other")]})
        first = retriever.retrieve("a", "account", limit=2)
        second = retriever.retrieve("a", "account", limit=2)
        self.assertEqual(["first", "second"], [item.bo_names[0] for item in first])
        self.assertEqual(first, second)
        self.assertEqual([], retriever.retrieve("missing", "account"))

    def test_retriever_caps_oversized_limit_at_five(self):
        entries = [
            DevelopmentKnowledge(text=f"account {number}", bo_names=[f"BO_{number}"])
            for number in range(8)
        ]
        retriever = StaticDevelopmentKnowledgeRetriever({"site": entries})

        recalled = retriever.retrieve("site", "account", limit=100)

        self.assertEqual(5, len(recalled))
        self.assertEqual([f"BO_{number}" for number in range(5)], [item.bo_names[0] for item in recalled])

    def test_chinese_term_matches_inside_longer_chinese_query(self):
        retriever = StaticDevelopmentKnowledgeRetriever({
            "site": [DevelopmentKnowledge(text="账户", bo_names=["BO_ACCOUNT"])]
        })
        recalled = retriever.retrieve("site", "查询账户明细")
        self.assertEqual(["BO_ACCOUNT"], [item.bo_names[0] for item in recalled])


class NamingSqlSelectorModelTests(unittest.TestCase):
    def test_development_knowledge_requires_text(self):
        with self.assertRaises(ValidationError):
            DevelopmentKnowledge()

    def test_models_are_strict_and_request_is_session_local(self):
        for model, payload in (
            (DataAccessSpec, {"unexpected": 1}),
            (DevelopmentKnowledge, {"text": "x", "unexpected": 1}),
            (NamingSqlSelectionRequest, {"site_id": "s", "query": "q", "project_id": "p"}),
            (NamingSqlSelectionRequest, {"site_id": "s", "query": "q", "source_key": "k"}),
        ):
            with self.subTest(model=model.__name__, payload=payload):
                with self.assertRaises(ValidationError):
                    model(**payload)
        self.assertNotIn("project_id", NamingSqlSelectionRequest.model_fields)
        self.assertNotIn("source_key", NamingSqlSelectionRequest.model_fields)

    def test_binding_plan_defaults_are_isolated(self):
        first, second = ParamBindingPlan(), ParamBindingPlan()
        first.unbound_params.append("x")
        self.assertEqual([], second.unbound_params)

    def test_selection_result_exposes_selected_bo_as_string(self):
        result = NamingSqlSelectionResult(status="needs_review", selected_bo="BO_AR_TRANS", review_mode="deterministic_fallback")
        self.assertEqual("BO_AR_TRANS", result.selected_bo)


def _loaded(profiles):
    registry = {"BO": _bo("BO", "orders")}
    return LoadedResource({}, registry, {}, {}, DomainRegistry(), {"BO": profiles})


class NamingSqlSelectionTests(unittest.TestCase):
    def test_binding_requires_matching_list_shape(self):
        def run(param_list, value_list):
            profile = NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="a", sql_name="a", params=[NamingSqlParamProfile(name="ids", data_type="integer", is_list=param_list)], is_full_table=False, search_text="orders")
            spec = DataAccessSpec(business_terms=["orders"], available_values=[AvailableValue(name="ids", source_ref="ctx.ids", data_type="int", is_list=value_list)])
            return NamingSqlSelector().select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded([profile]), spec)
        self.assertIsNotNone(run(True, True).selected)
        self.assertEqual("PARAM_UNBOUND", run(True, False).rejected_candidates[0].reject_codes[0])
        self.assertEqual("PARAM_UNBOUND", run(False, True).rejected_candidates[0].reject_codes[0])

    def test_semantic_binding_excludes_generic_id_and_requires_known_compatible_types(self):
        profile = NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="a", sql_name="a", params=[NamingSqlParamProfile(name="customer_id", data_type="integer")], is_full_table=False, search_text="orders")
        request = NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO")
        bad = DataAccessSpec(business_terms=["orders"], available_values=[AvailableValue(name="account_id", source_ref="account", data_type="int")])
        self.assertEqual("PARAM_UNBOUND", NamingSqlSelector().select(request, _loaded([profile]), bad).rejected_candidates[0].reject_codes[0])
        good = DataAccessSpec(business_terms=["orders"], available_values=[AvailableValue(name="customer identifier", source_ref="customer", data_type="java.lang.Long", semantic_tags=["customer"])])
        self.assertEqual(.85, NamingSqlSelector().select(request, _loaded([profile]), good).selected.binding_plan.bindings[0].confidence)
        wrong_type = good.model_copy(update={"available_values": [AvailableValue(name="customer identifier", source_ref="customer", data_type="timestamp", semantic_tags=["customer"])]})
        self.assertEqual("PARAM_UNBOUND", NamingSqlSelector().select(request, _loaded([profile]), wrong_type).rejected_candidates[0].reject_codes[0])

    def test_qualified_instant_is_temporal_not_numeric_int(self):
        profile = NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="a", sql_name="a", params=[NamingSqlParamProfile(name="customer_time", data_type="java.time.Instant")], is_full_table=False, search_text="orders")
        spec = DataAccessSpec(business_terms=["orders"], available_values=[AvailableValue(name="customer time", source_ref="customer", data_type="int", semantic_tags=["customer"])])
        result = NamingSqlSelector().select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded([profile]), spec)
        self.assertEqual("PARAM_UNBOUND", result.rejected_candidates[0].reject_codes[0])

    def test_filter_coverage_is_exact_not_substring(self):
        profile = NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="a", sql_name="a", filter_fields=["unrelated_identifier"], scope_tags=["id"], is_full_table=False, search_text="orders")
        result = NamingSqlSelector().select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded([profile]), DataAccessSpec(business_terms=["orders"], filter_requirements=["id = 3"]))
        self.assertEqual(["FILTER_NOT_COVERED"], result.rejected_candidates[0].reject_codes)

    def test_candidate_retriever_bounds_scoped_profiles_before_binding(self):
        class CapturingRetriever:
            seen = 0
            def retrieve(self, *, spec, profiles, knowledge, limit=30):
                self.seen = len(profiles)
                return profiles[:2]
        profiles = [NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id=str(i), sql_name=str(i), is_full_table=False, search_text="orders") for i in range(101)]
        retriever = CapturingRetriever()
        result = NamingSqlSelector(candidate_retriever=retriever).select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded(profiles), DataAccessSpec(business_terms=["orders"]))
        self.assertEqual(101, retriever.seen)
        self.assertEqual("0", result.selected.naming_sql_id)

    def test_local_candidate_retriever_clamps_and_prioritizes_knowledge_name(self):
        profiles = [NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id=str(i), sql_name=f"sql_{i}", is_full_table=False, search_text="common") for i in range(100)]
        knowledge = [DevelopmentKnowledge(text="common", naming_sql_names=["sql_99"])]
        recalled = LocalNamingSqlCandidateRetriever(max_candidates=999).retrieve(spec=DataAccessSpec(business_terms=["common"]), profiles=profiles, knowledge=knowledge)
        self.assertEqual(30, len(recalled))
        self.assertEqual("sql_99", recalled[0].sql_name)
    def test_exact_alias_semantic_tie_and_parameterless_binding(self):
        profiles = [
            NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="exact", sql_name="exact", params=[NamingSqlParamProfile(name="account_id", data_type="integer")], is_full_table=False, search_text="orders account"),
            NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="none", sql_name="none", params=[], is_full_table=False, search_text="orders"),
        ]
        spec = DataAccessSpec(business_terms=["orders"], available_values=[AvailableValue(name="Account-ID", source_ref="ctx.id", data_type="int")])
        result = NamingSqlSelector().select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded(profiles), spec)
        self.assertEqual("exact", result.selected.naming_sql_id)
        self.assertEqual(1.0, result.selected.binding_plan.bindings[0].confidence)

    def test_retrieved_alias_binds_and_equal_best_values_are_ambiguous(self):
        profile = NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="a", sql_name="a", params=[NamingSqlParamProfile(name="customer_id")], is_full_table=False, search_text="orders")
        knowledge = StaticDevelopmentKnowledgeRetriever({"s": [DevelopmentKnowledge(text="orders", param_aliases={"customer_id": ["client"]})]})
        one = DataAccessSpec(business_terms=["orders"], available_values=[AvailableValue(name="client", source_ref="ctx.client")])
        selected = NamingSqlSelector(knowledge).select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded([profile]), one)
        self.assertEqual(.95, selected.selected.binding_plan.bindings[0].confidence)
        tied = one.model_copy(update={"available_values": [AvailableValue(name="client", source_ref="a"), AvailableValue(name="client", source_ref="b")]})
        rejected = NamingSqlSelector(knowledge).select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded([profile]), tied)
        self.assertEqual(["PARAM_AMBIGUOUS"], rejected.rejected_candidates[0].reject_codes)

    def test_unbound_and_ambiguous_are_rejected_and_fulltable_is_fallback(self):
        profiles = [
            NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="bad", sql_name="bad", params=[NamingSqlParamProfile(name="year", data_type="date")], is_full_table=False, search_text="orders"),
            NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="full", sql_name="full", is_full_table=True, search_text="orders"),
        ]
        spec = DataAccessSpec(business_terms=["orders"], available_values=[AvailableValue(name="year", source_ref="x", data_type="integer")])
        result = NamingSqlSelector().select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded(profiles), spec)
        self.assertIsNone(result.selected)
        self.assertEqual(["PARAM_UNBOUND"], result.rejected_candidates[0].reject_codes)
        self.assertEqual(["full"], [x.naming_sql_id for x in result.fallback_candidates])

    def test_filter_coverage_and_valid_reviewer_choice(self):
        profiles = [NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id=x, sql_name=x, filter_fields=["year"], is_full_table=False, search_text="orders year") for x in ("a", "b")]
        class Reviewer:
            def review(self, *, spec, candidates): return "b"
        spec = DataAccessSpec(business_terms=["orders"], filter_requirements=["year"])
        result = NamingSqlSelector(reviewer=Reviewer()).select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded(profiles), spec)
        self.assertEqual(("b", "llm"), (result.selected.naming_sql_id, result.review_mode))

    def test_reviewer_sql_name_is_not_an_allowed_selection_key(self):
        profiles = [
            NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="id-a", sql_name="sql-a", is_full_table=False, search_text="orders"),
            NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="id-b", sql_name="sql-b", is_full_table=False, search_text="orders"),
        ]
        class Reviewer:
            def review(self, *, spec, candidates): return "sql-b"
        result = NamingSqlSelector(reviewer=Reviewer()).select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded(profiles), DataAccessSpec(business_terms=["orders"]))
        self.assertEqual(("id-a", "deterministic_fallback"), (result.selected.naming_sql_id, result.review_mode))

    def test_filter_expression_matches_profile_field(self):
        profile = NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="a", sql_name="a", filter_fields=["year"], is_full_table=False, search_text="orders")
        result = NamingSqlSelector().select(NamingSqlSelectionRequest(site_id="s", query="orders", bo_name="BO"), _loaded([profile]), DataAccessSpec(business_terms=["orders"], filter_requirements=["year = 2025"]))
        self.assertEqual("a", result.selected.naming_sql_id)

    def test_allow_fulltable_selects_only_bindable_and_no_profiles_needs_review(self):
        profile = NamingSqlProfile(site_id="s", bo_name="BO", naming_sql_id="full", sql_name="full", params=[], is_full_table=True)
        result = NamingSqlSelector().select(NamingSqlSelectionRequest(site_id="s", query="x", bo_name="BO"), _loaded([profile]), DataAccessSpec(allow_full_table=True))
        self.assertEqual("full", result.selected.naming_sql_id)
        empty = NamingSqlSelector().select(NamingSqlSelectionRequest(site_id="s", query="x", bo_name="BO"), _loaded([]), DataAccessSpec())
        self.assertEqual(("needs_review", None, "deterministic_fallback"), (empty.status, empty.selected, empty.review_mode))


def _bo(name, description="", properties=()):
    return BoRegistry(
        resource_id=name.lower(), bo_name=name, bo_desc=description,
        property_list=[PropertyTerm(field_name=field, description=desc, data_type=DataTypeEnum.basic, data_type_name="string") for field, desc in properties],
    )


def _profile(bo_name, search_text="", filter_fields=(), scope_tags=()):
    return NamingSqlProfile(
        site_id="s", bo_name=bo_name, naming_sql_id=f"{bo_name}-sql", sql_name="hidden command profile",
        filter_fields=list(filter_fields), scope_tags=list(scope_tags), search_text=search_text,
    )


class BoResolverTests(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "BO_AR_TRANS": _bo("BO_AR_TRANS", "account transaction records", (("ACCOUNT_ID", "account identifier"),)),
            "BO_FREE_RESOURCE": _bo("BO_FREE_RESOURCE", "free resource inventory", (("RESOURCE_ID", "resource identifier"),)),
        }
        self.profiles = {
            "BO_AR_TRANS": [_profile("BO_AR_TRANS", "account transaction", ("ACCOUNT_ID",), ("account",))],
            "BO_FREE_RESOURCE": [_profile("BO_FREE_RESOURCE", "free resource", ("RESOURCE_ID",), ("resource",))],
        }

    def test_explicit_valid_is_normalized_and_does_not_call_reviewer(self):
        class Reviewer:
            def review(self, **kwargs):
                raise AssertionError("reviewer must not run")
        result = BoResolver(Reviewer()).resolve(explicit_bo="  BO_AR_TRANS  ", spec=DataAccessSpec(), bo_registry=self.registry, profiles=self.profiles)
        self.assertEqual(("BO_AR_TRANS", "not_required"), (result.bo_name, result.review_mode))

    def test_invalid_explicit_and_empty_registry_raise_bo_not_loaded(self):
        resolver = BoResolver()
        with self.assertRaisesRegex(ValueError, "BO_NOT_LOADED"):
            resolver.resolve(explicit_bo="BO_MISSING", spec=DataAccessSpec(), bo_registry=self.registry, profiles=self.profiles)
        with self.assertRaisesRegex(ValueError, "BO_NOT_LOADED: no BO candidates"):
            resolver.resolve(explicit_bo=None, spec=DataAccessSpec(), bo_registry={}, profiles={})

    def test_hint_and_semantic_recall_prefers_account_transactions(self):
        spec = DataAccessSpec(business_terms=["account records"], bo_hints=["BO_AR_TRANS"], filter_requirements=["account id"])
        result = BoResolver().resolve(explicit_bo=None, spec=spec, bo_registry=self.registry, profiles=self.profiles)
        self.assertEqual(("BO_AR_TRANS", "deterministic_fallback"), (result.bo_name, result.review_mode))
        self.assertTrue(result.reasons)

    def test_valid_reviewer_can_choose_supplied_lower_ranked_candidate(self):
        class Reviewer:
            def review(self, *, spec, candidates):
                return candidates[-1].bo_name
        result = BoResolver(Reviewer()).resolve(explicit_bo=None, spec=DataAccessSpec(business_terms=["account"]), bo_registry=self.registry, profiles=self.profiles)
        self.assertEqual(("BO_FREE_RESOURCE", "llm"), (result.bo_name, result.review_mode))

    def test_invalid_none_and_throwing_reviewers_fall_back_to_top_one(self):
        class NoneReviewer:
            def review(self, **kwargs):
                return None
        class InventingReviewer:
            def review(self, **kwargs):
                return "BO_INVENTED"
        class Throwing:
            def review(self, **kwargs):
                raise RuntimeError("offline")
        for reviewer in (NoneReviewer(), InventingReviewer(), Throwing()):
            with self.subTest(reviewer=reviewer):
                result = BoResolver(reviewer).resolve(explicit_bo=None, spec=DataAccessSpec(business_terms=["account"]), bo_registry=self.registry, profiles=self.profiles)
                self.assertEqual(("BO_AR_TRANS", "deterministic_fallback"), (result.bo_name, result.review_mode))

    def test_unhashable_reviewer_results_fall_back_to_top_one(self):
        class MalformedReviewer:
            def __init__(self, result):
                self.result = result

            def review(self, **kwargs):
                return self.result

        for malformed in ([], {}):
            with self.subTest(malformed=malformed):
                result = BoResolver(MalformedReviewer(malformed)).resolve(
                    explicit_bo=None,
                    spec=DataAccessSpec(business_terms=["account"]),
                    bo_registry=self.registry,
                    profiles=self.profiles,
                )
                self.assertEqual(("BO_AR_TRANS", "deterministic_fallback"), (result.bo_name, result.review_mode))

    def test_reviewer_receives_at_most_five_compact_candidates(self):
        captured = []
        class Reviewer:
            def review(self, *, spec, candidates):
                captured.extend(candidates)
                return None
        registry = {f"BO_{index}": _bo(f"BO_{index}", "common") for index in range(8)}
        profiles = {name: [_profile(name, "common confidential_sql_text")] for name in registry}
        BoResolver(Reviewer(), max_candidates=99).resolve(explicit_bo=None, spec=DataAccessSpec(business_terms=["common"]), bo_registry=registry, profiles=profiles)
        self.assertLessEqual(len(captured), 5)
        self.assertTrue(all(type(item) is BoCandidate for item in captured))
        self.assertTrue(all("confidential_sql_text" not in repr(item) for item in captured))

    def test_malicious_reviewer_cannot_mutate_allowed_names_or_fallback_ranking(self):
        class MaliciousReviewer:
            def review(self, *, spec, candidates):
                candidates[0].bo_name = "BO_INVENTED"
                candidates[0].score = -9999.0
                candidates.append(BoCandidate(bo_name="BO_INVENTED", score=9999.0, summary="injected"))
                return "BO_INVENTED"

        result = BoResolver(MaliciousReviewer()).resolve(
            explicit_bo=None,
            spec=DataAccessSpec(business_terms=["account"]),
            bo_registry=self.registry,
            profiles=self.profiles,
        )

        self.assertEqual(("BO_AR_TRANS", "deterministic_fallback"), (result.bo_name, result.review_mode))

    def test_malicious_reviewer_cannot_mutate_caller_spec(self):
        class MaliciousReviewer:
            def review(self, *, spec, candidates):
                spec.business_terms.append("injected")
                spec.bo_hints.clear()
                return None

        spec = DataAccessSpec(business_terms=["account"], bo_hints=["BO_AR_TRANS"])
        BoResolver(MaliciousReviewer()).resolve(
            explicit_bo=None,
            spec=spec,
            bo_registry=self.registry,
            profiles=self.profiles,
        )

        self.assertEqual(["account"], spec.business_terms)
        self.assertEqual(["BO_AR_TRANS"], spec.bo_hints)

    def test_zero_scores_choose_alphabetically_and_unknown_hint_is_not_candidate(self):
        registry = {"BO_Z": _bo("BO_Z"), "BO_A": _bo("BO_A")}
        result = BoResolver().resolve(explicit_bo=None, spec=DataAccessSpec(bo_hints=["BO_MISSING"]), bo_registry=registry, profiles={})
        self.assertEqual("BO_A", result.bo_name)

    def test_cjk_semantic_overlap_selects_account_and_free_resource(self):
        registry = {
            "BO_ACCOUNT": _bo("BO_ACCOUNT", "账户交易明细"),
            "BO_FREE": _bo("BO_FREE", "免费资源列表"),
        }
        for term, expected in (("查询账户明细", "BO_ACCOUNT"), ("查找免费资源", "BO_FREE")):
            with self.subTest(term=term):
                result = BoResolver().resolve(explicit_bo=None, spec=DataAccessSpec(business_terms=[term]), bo_registry=registry, profiles={})
                self.assertEqual(expected, result.bo_name)


if __name__ == "__main__":
    unittest.main()
