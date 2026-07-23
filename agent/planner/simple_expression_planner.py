import json
from typing import Any

from agent.environment.environment import FilteredEnvironment
from agent.context_pack import ContextPack, ContextPackPromptRenderer
from agent.expression_generation.expression_type_validation import SimpleExpressionPlan
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.expression_generation.expression_spec import ExpressionSpec
from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.llm_planner import (
    _summarize_expression_scope_json,
    _summarize_expression_skills_json,
    _summarize_filtered_environment_json,
    _summarize_typed_context_json,
)


class SimpleExpressionPlanner:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    @property
    def is_usable(self) -> bool:
        return self.client.is_usable

    def plan(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        filtered_env: FilteredEnvironment,
        typed_context: TypedExpressionContext,
        context_pack: ContextPack | None = None,
        expression_spec: ExpressionSpec | None = None,
        retry_feedback: dict[str, Any] | None = None,
    ) -> SimpleExpressionPlan:
        if not self.is_usable:
            raise RuntimeError("Simple expression planner is not usable")
        response = generate_by_llm(
            prompt_template="simple_expression_planner", llm_name="base", lang="zh", client=self.client,
            user_requirement=user_query,
            node_info_json=json.dumps(node_info.model_dump(), ensure_ascii=False),
            resources_json=json.dumps({
                **json.loads(_summarize_filtered_environment_json(filtered_env)),
                "context_pack": json.loads(ContextPackPromptRenderer().render_json(context_pack)) if context_pack else {},
            }, ensure_ascii=False, separators=(",", ":")),
            typed_context_json=_summarize_typed_context_json(typed_context),
            expression_scope_json=_summarize_expression_scope_json(expression_spec),
            expression_skills_json=_summarize_expression_skills_json(expression_spec),
            retry_feedback_json=json.dumps(retry_feedback or {}, ensure_ascii=False, separators=(",", ":")),
        )
        return SimpleExpressionPlan.model_validate(response)
