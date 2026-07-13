import pytest

from agent.context_pack.resource_router import FastContextResourceRouter


class Client:
    def __init__(self, usable=True):
        self.is_usable = usable


@pytest.mark.parametrize(("value", "expected"), [(True, True), (False, False)])
def test_router_accepts_only_strict_boolean_decision(value, expected):
    calls = []
    def decide(**kwargs):
        calls.append(kwargs)
        return {"use_current_tree": value}
    result = FastContextResourceRouter(client=Client(), decision_fn=decide).route(
        query="use sibling field", node={"node_id": "n", "name": "amount", "children": [1]},
        parent_node={"node_id": "p", "annotation": "parent", "children": [2]},
    )
    assert result.use_current_tree is expected
    assert result.fallback is False
    assert len(calls) == 1
    assert "children" not in calls[0]["node_info_json"]
    assert "children" not in calls[0]["parent_node_info_json"]


@pytest.mark.parametrize("response", [None, [], {}, {"use_current_tree": 1},
                                       {"use_current_tree": "true"}])
def test_invalid_output_falls_back_to_all_resources_without_retry(response):
    calls = []
    def decide(**kwargs):
        calls.append(kwargs)
        return response
    result = FastContextResourceRouter(client=Client(), decision_fn=decide).route(
        query="q", node={"node_id": "n"}, parent_node=None,
    )
    assert result.use_current_tree is True
    assert result.fallback is True
    assert len(calls) == 1


def test_unusable_client_falls_back_without_calling_llm():
    def fail(**kwargs):
        raise AssertionError("must not call")
    result = FastContextResourceRouter(client=Client(False), decision_fn=fail).route(
        query="q", node={"node_id": "n"}, parent_node=None,
    )
    assert result.use_current_tree is True and result.fallback is True


def test_llm_exception_falls_back_without_retry_or_leaking_error():
    calls = []
    def decide(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("private")
    result = FastContextResourceRouter(client=Client(), decision_fn=decide).route(
        query="q", node={"node_id": "n"}, parent_node=None,
    )
    assert result.use_current_tree is True and result.fallback is True
    assert len(calls) == 1
