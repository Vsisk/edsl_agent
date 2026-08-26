from agent.business_context import LLMBusinessScopeClassifier, build_business_path_context


class ScopeClassifier:
    def __init__(self, scope):
        self.scope = scope
        self.calls = []

    def classify(self, **kwargs):
        self.calls.append(kwargs)
        return self.scope


def test_builds_business_path_from_node_path_xml_names_and_uses_leaf_scope():
    tree = {
        "mapping_content": {
            "xml_name_property": {"xml_name": "Bill"},
            "children": [
                {
                    "xml_name_property": {"xml_name": "AcctInfo"},
                    "children": [
                        {
                            "xml_name_property": {"xml_name": "Subscriber"},
                            "children": [
                                {"xml_name_property": {"xml_name": "ServiceNo"}}
                            ],
                        }
                    ],
                }
            ],
        }
    }

    classifier = ScopeClassifier("sub")

    context = build_business_path_context(
        edsl_tree=tree,
        node_path="$.mapping_content.children[0].children[0].children[0]",
        current_node={"xml_name_property": {"xml_name": "ServiceNo"}},
        scope_classifier=classifier,
    )

    assert context.business_path == ["Bill", "AcctInfo", "Subscriber", "ServiceNo"]
    assert context.business_path_text == "Bill/AcctInfo/Subscriber/ServiceNo"
    assert context.business_level == "sub"
    assert context.business_scope == "sub"
    assert context.node_path == "$.mapping_content.children[0].children[0].children[0]"
    assert classifier.calls == [{
        "node_path": "$.mapping_content.children[0].children[0].children[0]",
        "business_path": ["Bill", "AcctInfo", "Subscriber", "ServiceNo"],
        "current_node": {"xml_name_property": {"xml_name": "ServiceNo"}},
    }]


def test_builds_business_path_falls_back_to_current_node_when_path_cannot_resolve():
    context = build_business_path_context(
        edsl_tree=None,
        node_path="$.missing",
        current_node={"xml_name_property": {"xml_name": "AcctBalance"}},
        scope_classifier=ScopeClassifier("acct"),
    )

    assert context.business_path == ["AcctBalance"]
    assert context.business_level == "acct"


def test_business_level_uses_llm_scope_classifier_not_name_rules():
    context = build_business_path_context(
        edsl_tree={
            "mapping_content": {
                "xml_name_property": {"xml_name": "UserInfo"},
                "children": [
                    {"xml_name_property": {"xml_name": "InvoiceAmount"}}
                ],
            }
        },
        node_path="$.mapping_content.children[0]",
        current_node={"xml_name_property": {"xml_name": "InvoiceAmount"}},
        scope_classifier=ScopeClassifier("acct"),
    )

    assert context.business_path == ["UserInfo", "InvoiceAmount"]
    assert context.business_level == "acct"


def test_llm_business_scope_classifier_uses_node_path_and_business_path():
    calls = []

    def decision_fn(**kwargs):
        calls.append(kwargs)
        return {"scope": "bill"}

    scope = LLMBusinessScopeClassifier(decision_fn=decision_fn).classify(
        node_path="$.mapping_content.children[0]",
        business_path=["BillInfo", "Amount"],
        current_node={"xml_name_property": {"xml_name": "Amount"}},
    )

    assert scope == "bill"
    assert calls[0]["prompt_template"] == "business_scope_classifier"
    assert calls[0]["node_path"] == "$.mapping_content.children[0]"
    assert calls[0]["business_path_text"] == "BillInfo/Amount"
    assert '"BillInfo"' in calls[0]["business_path_json"]
    assert '"Amount"' in calls[0]["current_node_json"]
