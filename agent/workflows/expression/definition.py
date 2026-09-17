from __future__ import annotations

from agent.workflow.context import ContextPolicy
from agent.workflow.runtime.definition import WorkflowDefinition
from agent.workflow.transition import RetryPolicy, TransitionPolicy, TransitionRule
from agent.workflows.expression.failure_classifier import ExpressionFailureClassifier


class ExpressionWorkflowFactory:
    def __init__(self, **dependencies) -> None:
        self.dependencies = dependencies

    def create_definition(self) -> WorkflowDefinition:
        from agent.expression_generate_op.stages import (
            ASTValidationStage,
            ASTValidationStageContext,
            ExpressionGenerateStage,
            ExpressionGenerateStageContext,
            FinalizeStage,
            FinalizeStageContext,
            ResourceSearchStage,
            ResourceSearchStageContext,
            SpecAnalysisStage,
            SpecAnalysisStageContext,
        )

        spec_stage = SpecAnalysisStage(
            spec_generator=self.dependencies["spec_generator"],
            route_fn=self.dependencies["route_fn"],
            infer_expected_type_fn=self.dependencies["infer_expected_type_fn"],
        )
        resource_stage = ResourceSearchStage(
            target_searcher=self.dependencies["target_searcher"],
            typed_context_builder=self.dependencies["typed_context_builder"],
            merge_sql_env_fn=self.dependencies["merge_sql_env_fn"],
            infer_expected_type_fn=self.dependencies["infer_expected_type_fn"],
            type_registry=self.dependencies["type_registry"],
            method_registry=self.dependencies["method_registry"],
        )
        generate_stage = ExpressionGenerateStage(
            llm_planner=self.dependencies["llm_planner"],
        )
        validation_stage = ASTValidationStage(
            build_validation_context_fn=self.dependencies["build_validation_context_fn"],
        )
        finalize_stage = FinalizeStage(
            type_ref_to_return_type_fn=self.dependencies["type_ref_to_return_type_fn"],
        )
        failure_classifier = ExpressionFailureClassifier()

        _bind_stage_metadata(
            spec_stage,
            input_model=SpecAnalysisStageContext,
            context_policy=ContextPolicy(
                input_model=SpecAnalysisStageContext,
                harness_bindings={
                    "request": "request",
                    "resources_context": "resources_context",
                    "context_pack": "context_pack",
                    "node_info": "node_info",
                    "retry_feedback": "retry_feedback",
                },
                knowledge_ids=(
                    "expression.context",
                    "expression.return-type",
                ),
                knowledge_scope="expression",
            ),
            environment_bindings={
                "request": "request",
                "resources_context": "resources_context",
                "context_pack": "context_pack",
                "node_info": "node_info",
                "retry_feedback": "retry_feedback",
            },
            failure_stage="spec",
            failure_classifier=failure_classifier,
        )
        _bind_stage_metadata(
            resource_stage,
            input_model=ResourceSearchStageContext,
            context_policy=ContextPolicy(
                input_model=ResourceSearchStageContext,
                artifact_bindings={"spec": "spec"},
                harness_bindings={
                    "request": "request",
                    "resources_context": "resources_context",
                    "context_pack": "context_pack",
                    "node_info": "node_info",
                    "retry_feedback": "retry_feedback",
                    "sql_branch_filtered_env": "initial_filtered_env",
                },
                tool_names=(
                    "search_context",
                    "search_bo",
                    "search_namingsql",
                    "search_reference_node",
                    "inspect_return_type",
                ),
                skill_names=("resource_search",),
                knowledge_tags=("resource",),
                knowledge_scope="expression",
                downstream_feedback_field="downstream_feedback",
            ),
            artifact_bindings={"spec": "spec"},
            environment_bindings={
                "request": "request",
                "resources_context": "resources_context",
                "context_pack": "context_pack",
                "node_info": "node_info",
                "retry_feedback": "retry_feedback",
                "sql_branch_filtered_env": "initial_filtered_env",
            },
            failure_stage="resource_filter",
            failure_classifier=failure_classifier,
        )
        _bind_stage_metadata(
            generate_stage,
            input_model=ExpressionGenerateStageContext,
            context_policy=ContextPolicy(
                input_model=ExpressionGenerateStageContext,
                artifact_bindings={
                    "spec": "spec",
                    "filtered_env": "resources",
                    "typed_context": "typed_context",
                },
                harness_bindings={
                    "request": "request",
                    "context_pack": "context_pack",
                    "node_info": "node_info",
                    "retry_feedback": "retry_feedback",
                },
                tool_names=("inspect_return_type",),
                skill_names=(
                    "expression_generation",
                    "expression_repair",
                ),
                knowledge_tags=("generation", "return-type", "ast"),
                knowledge_scope="expression",
                downstream_feedback_field="downstream_feedback",
            ),
            artifact_bindings={
                "spec": "spec",
                "filtered_env": "resources",
                "typed_context": "typed_context",
            },
            environment_bindings={
                "request": "request",
                "context_pack": "context_pack",
                "node_info": "node_info",
                "retry_feedback": "retry_feedback",
            },
            failure_stage="planner",
            failure_classifier=failure_classifier,
        )
        _bind_stage_metadata(
            validation_stage,
            input_model=ASTValidationStageContext,
            context_policy=ContextPolicy(
                input_model=ASTValidationStageContext,
                artifact_bindings={
                    "ast": "ast",
                    "filtered_env": "resources",
                    "typed_context": "typed_context",
                },
                harness_bindings={"resources_context": "resources_context"},
                tool_names=(
                    "validate_ast",
                    "inspect_return_type",
                ),
                skill_names=("expression_repair",),
                knowledge_tags=("validation", "return-type", "ast"),
                knowledge_scope="expression",
                downstream_feedback_field="downstream_feedback",
            ),
            artifact_bindings={
                "ast": "ast",
                "filtered_env": "resources",
                "typed_context": "typed_context",
            },
            environment_bindings={"resources_context": "resources_context"},
            failure_stage="validation",
            terminal_failure_reason="validation_failed",
            failure_classifier=failure_classifier,
        )
        _bind_stage_metadata(
            finalize_stage,
            input_model=FinalizeStageContext,
            context_policy=ContextPolicy(
                input_model=FinalizeStageContext,
                artifact_bindings={
                    "ast": "ast",
                    "validation": "validation",
                    "typed_context": "typed_context",
                },
                harness_bindings={
                    "request": "request",
                    "context_pack": "context_pack",
                    "node_info": "node_info",
                },
                skill_names=("expression_generation",),
                knowledge_ids=(
                    "expression.return-type",
                    "expression.ast",
                ),
                knowledge_scope="expression",
            ),
            artifact_bindings={
                "ast": "ast",
                "validation": "validation",
                "typed_context": "typed_context",
            },
            environment_bindings={
                "request": "request",
                "context_pack": "context_pack",
                "node_info": "node_info",
            },
            failure_stage="pipeline",
            failure_classifier=failure_classifier,
        )

        return WorkflowDefinition(
            name="expression_generation",
            entry_stage="spec_analysis",
            stages={
                "spec_analysis": spec_stage,
                "resource_search": resource_stage,
                "expression_generate": generate_stage,
                "ast_validation": validation_stage,
                "finalize": finalize_stage,
            },
            default_transitions={
                "spec_analysis": "resource_search",
                "resource_search": "expression_generate",
                "expression_generate": "ast_validation",
                "ast_validation": "finalize",
                "finalize": None,
            },
            terminal_stages={"finalize"},
            transition_policy=TransitionPolicy(
                rules=(
                    TransitionRule(
                        from_stage="ast_validation",
                        to_stage="expression_generate",
                        observation_codes=("SYNTAX_ERROR", "FUNCTION_ARGUMENT_ERROR"),
                    ),
                    TransitionRule(
                        from_stage="ast_validation",
                        to_stage="resource_search",
                        observation_codes=("UNKNOWN_PROPERTY", "TYPE_MISMATCH"),
                    ),
                    TransitionRule(
                        from_stage="resource_search",
                        to_stage="spec_analysis",
                        observation_codes=("SPEC_INSUFFICIENT",),
                    ),
                    TransitionRule(
                        from_stage="expression_generate",
                        to_stage="resource_search",
                        observation_codes=("RESOURCE_NOT_FOUND",),
                    ),
                )
            ),
            retry_policy=RetryPolicy(),
        )


def _bind_stage_metadata(
    stage,
    *,
    input_model,
    context_policy: ContextPolicy | None = None,
    artifact_bindings: dict[str, str] | None = None,
    environment_bindings: dict[str, str] | None = None,
    failure_stage: str,
    terminal_failure_reason: str | None = None,
    failure_classifier: ExpressionFailureClassifier | None = None,
) -> None:
    stage.input_model = input_model
    stage.artifact_bindings = artifact_bindings or {}
    stage.optional_artifact_bindings = {}
    stage.environment_bindings = environment_bindings or {}
    stage.context_policy = context_policy or ContextPolicy(
        input_model=input_model,
        artifact_bindings=stage.artifact_bindings,
        optional_artifact_bindings=stage.optional_artifact_bindings,
        harness_bindings=stage.environment_bindings,
    )
    stage.failure_stage = failure_stage
    stage.terminal_failure_reason = terminal_failure_reason
    stage.failure_classifier = failure_classifier
