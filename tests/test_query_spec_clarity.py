from agent.spec_orchestration.spec_clarity import QuerySpecClarityAnalyzer


def test_query_spec_clarity_analyzer_accepts_only_explicit_boolean_result():
    calls = []

    def decide(**kwargs):
        calls.append(kwargs)
        return {"is_explicit_spec": True, "reason": "resource paths are explicit"}

    analyzer = QuerySpecClarityAnalyzer(decision_fn=decide)

    assert analyzer.is_explicit_spec(
        query="use $ctx$.customer.id",
        node_info={"node_name": "customerId"},
        expected_type={"data_type": "basic", "data_type_name": "String"},
        request={"site_id": "site"},
        context_pack={"status": "complete"},
    ) is True
    assert calls[0]["prompt_template"] == "query_spec_clarity"


def test_query_spec_clarity_analyzer_treats_invalid_output_as_not_explicit():
    analyzer = QuerySpecClarityAnalyzer(
        decision_fn=lambda **_: {"is_explicit_spec": "yes"}
    )

    assert analyzer.is_explicit_spec(query="customer name") is False
