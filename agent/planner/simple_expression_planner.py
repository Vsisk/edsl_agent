import json

from agent.environment.environment import FilteredEnvironment
from agent.expression_generation.expression_type_validation import SimpleExpressionPlan
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.llm_planner import _summarize_filtered_environment_json, _summarize_typed_context_json


class SimpleExpressionPlanner:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    @property
    def is_usable(self) -> bool:
        return self.client.is_usable

    def plan(self, *, node_info: NodeDef, user_query: str, filtered_env: FilteredEnvironment,
             typed_context: TypedExpressionContext) -> SimpleExpressionPlan:
        if not self.is_usable:
            raise RuntimeError("Simple expression planner is not usable")
        response = generate_by_llm(
            prompt_template="simple_expression_planner", llm_name="base", lang="zh", client=self.client,
            user_requirement=user_query,
            node_info_json=json.dumps(node_info.model_dump(), ensure_ascii=False),
            resources_json=_summarize_filtered_environment_json(filtered_env),
            typed_context_json=_summarize_typed_context_json(typed_context),
        )
        return SimpleExpressionPlan.model_validate(response)
