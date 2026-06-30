import unittest

from pydantic import ValidationError

from agent.naming_sql_selector import (
    AvailableValue,
    DataAccessSpec,
    DataAccessSpecGenerator,
    DevelopmentKnowledge,
    NamingSqlSelectionRequest,
    StaticDevelopmentKnowledgeRetriever,
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


class NamingSqlSelectorModelTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
