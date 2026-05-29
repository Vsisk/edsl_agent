import unittest

from agent.environment.resource_search_tool import ResourceKeywordSearchTool


class ResourceKeywordSearchToolTest(unittest.TestCase):
    def test_search_returns_matching_item_indices(self):
        tool = ResourceKeywordSearchTool()
        items = [
            "BB_BAK_TRANS BB_BAK_TRANS_queryDataLoadData",
            "CUSTOM_ACCOUNT CUSTOM_ACCOUNT_queryById",
        ]

        self.assertEqual(tool.search(items, "BB_BAK_TRANS_queryDataLoadData"), [0])

    def test_search_matches_compact_keyword(self):
        tool = ResourceKeywordSearchTool()
        items = ["$ctx$.billStatement.CUST_ID", "$ctx$.bill_id"]

        self.assertEqual(tool.search(items, "ctx billStatement CUST ID"), [0])

    def test_search_returns_empty_for_missing_keyword(self):
        tool = ResourceKeywordSearchTool()

        self.assertEqual(tool.search(["CustCallMask"], "MissingFunc"), [])


if __name__ == "__main__":
    unittest.main()
