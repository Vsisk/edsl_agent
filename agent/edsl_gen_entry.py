from typing import Any

from agent.environment.environment import build_filtered_environment
from agent.environment.resource_filter import LLMResourceFilter
from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.generator import generate_expression
from agent.expression_generation.ast.validator import validate_ast
from agent.models import GenerateDSLRequest, GenerateDSLResponse
from agent.planner.llm_planner import LLMPlanner
from agent.resource_manager.loader.resource_loader import ResourceLoader, resource_loader as default_resource_loader


class DSLAgent:
    def __init__(
        self,
        *,
        resource_loader: ResourceLoader | None = None,
        llm_resource_filter: Any | None = None,
        llm_planner: LLMPlanner | None = None,
    ):
        self.resource_loader = resource_loader or default_resource_loader
        self.llm_resource_filter = llm_resource_filter or LLMResourceFilter()
        self.llm_planner = llm_planner or LLMPlanner()

    def generate_dsl(self, request: GenerateDSLRequest) -> GenerateDSLResponse:
        try:
            registry = self.resource_loader.load_resource(
                request.site_id,
                request.project_id,
                request.edsl_tree,
            )
            filtered_env = build_filtered_environment(
                node_info=request.node,
                user_query=request.user_requirement,
                registry=registry,
                llm_resource_filter=self.llm_resource_filter,
            )
            plan = self.llm_planner.plan(
                node_info=request.node,
                user_query=request.user_requirement,
                filtered_env=filtered_env,
            )
            ast = build_ast(plan)
            validate_ast(ast)
            dsl = generate_expression(ast)
        except Exception as exc:
            return GenerateDSLResponse(
                success=False,
                failure_reason=f"expression generation failed: {exc}",
            )

        return GenerateDSLResponse(success=True, dsl=dsl, failure_reason="")
