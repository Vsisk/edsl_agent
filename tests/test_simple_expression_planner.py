from agent.environment.environment import FilteredEnvironment
from agent.expression_generation.expression_type_validation import SimpleExpressionPlan
from agent.expression_generation.typed_context import TypedExpressionContext, TypedRootValue
from agent.models import NodeDef
from agent.planner.simple_expression_planner import SimpleExpressionPlanner
from tests.test_llm_planner import FakeClient


def test_simple_planner_returns_plan_and_includes_typed_context():
    client = FakeClient(['{"definitions":[],"return_expr":"$ctx$.name.length()"}'])
    result = SimpleExpressionPlanner(client=client).plan(
        node_info=NodeDef(node_id="n", node_path="$.n", node_name="n"),
        user_query="length",
        filtered_env=FilteredEnvironment(),
        typed_context=TypedExpressionContext(root_values=[TypedRootValue(expr="$ctx$.name", source_type="context", return_type="basic.String")]),
    )
    assert isinstance(result, SimpleExpressionPlan)
    assert "$ctx$.name" in client.calls[0]["prompt"]
