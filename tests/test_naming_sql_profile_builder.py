import unittest

from pydantic import ValidationError

from agent.naming_sql_selector import NamingSqlProfile, NamingSqlProfileBuilder
from agent.resource_manager.models import NamingSqlDefTerm, ParamTerm


def definition(sql_command: str | None) -> NamingSqlDefTerm:
    return NamingSqlDefTerm(
        naming_sql_id="sql-1",
        sql_name="AccountTransactions",
        label_name="Account transaction search",
        sql_description="Find dated account transactions",
        sql_command=sql_command,
        param_list=[
            ParamTerm(param_name="ACCT_ID", data_type="basic", data_type_name="long"),
            ParamTerm(param_name="START_DATE", data_type="basic", data_type_name="Date"),
        ],
    )


class NamingSqlProfileBuilderTest(unittest.TestCase):
    def test_extracts_effective_predicate_fields_and_copies_params(self):
        profile = NamingSqlProfileBuilder().build(
            "site-a",
            "BB_TRANS",
            definition(
                "SELECT * FROM BB_TRANS t WHERE 1=1 "
                "AND t.ACCT_ID = :ACCT_ID AND TRANS_DATE >= :START_DATE"
            ),
        )

        self.assertEqual(profile.filter_fields, ["ACCT_ID", "TRANS_DATE"])
        self.assertFalse(profile.is_full_table)
        self.assertEqual([param.name for param in profile.params], ["ACCT_ID", "START_DATE"])
        self.assertEqual(profile.params[0].data_type, "long")
        self.assertFalse(profile.params[0].is_list)
        self.assertEqual(profile.site_id, "site-a")
        self.assertNotIn("project_id", NamingSqlProfile.model_fields)
        self.assertNotIn("source_key", NamingSqlProfile.model_fields)
        self.assertIn("ACCT", profile.scope_tags)
        self.assertIn("account", profile.scope_tags)
        self.assertNotIn("Account transaction search", profile.scope_tags)
        self.assertEqual(profile.search_text, " ".join(profile.scope_tags).lower())

    def test_tautology_only_is_full_table(self):
        profile = NamingSqlProfileBuilder().build("site-a", "BB_TRANS", definition("SELECT * FROM BB_TRANS WHERE 1=1"))
        self.assertEqual(profile.filter_fields, [])
        self.assertTrue(profile.is_full_table)

    def test_missing_sql_is_conservatively_full_table(self):
        profile = NamingSqlProfileBuilder().build("site-a", "BB_TRANS", definition(None))
        self.assertTrue(profile.is_full_table)

    def test_malformed_predicate_without_rhs_is_full_table(self):
        profile = NamingSqlProfileBuilder().build("site-a", "BB_TRANS", definition("SELECT * FROM T WHERE ACCT_ID ="))
        self.assertEqual(profile.filter_fields, [])
        self.assertTrue(profile.is_full_table)

    def test_profile_forbids_unknown_fields(self):
        with self.assertRaises(ValidationError):
            NamingSqlProfile(
                site_id="site-a", bo_name="BO", naming_sql_id="id", sql_name="name", project_id="p"
            )


if __name__ == "__main__":
    unittest.main()
