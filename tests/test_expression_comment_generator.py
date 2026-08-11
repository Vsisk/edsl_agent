from agent.expression_generation.expression_comment_generator import LLMExpressionCommentGenerator
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.models import NodeDef


class Settings:
    is_usable = True

    def model_for(self, llm_name):
        return "test-model"


class Client:
    def __init__(self, content):
        self.settings = Settings()
        self.content = content
        self.calls = []

    @property
    def is_usable(self):
        return True

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.content


def test_llm_expression_comment_generator_returns_comment_plan():
    client = Client('{"comments":[{"line":1,"placement":"inline","text":"return name"}]}')
    generator = LLMExpressionCommentGenerator(client=client)

    comments = generator.generate_comments(
        expression="$ctx$.name",
        user_query="use name",
        node_info=NodeDef(node_id="n", node_path="$.n", node_name="name"),
        typed_context=TypedExpressionContext(),
    )

    assert comments == [{"line": 1, "placement": "inline", "text": "return name"}]
    assert "$ctx$.name" in client.calls[0]["prompt"]
    assert client.calls[0]["model"] == "test-model"


def test_llm_expression_comment_generator_falls_back_to_empty_comments():
    class FailingClient(Client):
        def complete(self, **kwargs):
            raise RuntimeError("bad key")

    comments = LLMExpressionCommentGenerator(
        client=FailingClient("{}")
    ).generate_comments(
        expression="$ctx$.name",
        user_query="use name",
        node_info=NodeDef(node_id="n", node_path="$.n", node_name="name"),
        typed_context=TypedExpressionContext(),
    )

    assert comments == []
