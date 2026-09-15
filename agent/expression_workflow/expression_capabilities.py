from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent.expression_workflow.capabilities import (
    CapabilityRegistries,
    KnowledgeDefinition,
    SkillDefinition,
    ToolDefinition,
)


EXPRESSION_WORKFLOW_NAME = "expression_generation"
_KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "docs" / "knowledge" / "expression"


def create_expression_capability_registries(
    *,
    tool_callables: dict[str, Callable[..., Any]] | None = None,
) -> CapabilityRegistries:
    registries = CapabilityRegistries()
    _register_expression_tools(registries, tool_callables or {})
    _register_expression_skills(registries)
    _register_expression_knowledge(registries)
    return registries


def _register_expression_tools(
    registries: CapabilityRegistries,
    tool_callables: dict[str, Callable[..., Any]],
) -> None:
    for name, description in {
        "search_context": "Search visible context resources for the current expression task.",
        "search_bo": "Search business object resources for the current expression task.",
        "search_namingsql": "Search naming SQL resources for the current expression task.",
        "inspect_return_type": "Inspect and normalize target or source return type metadata.",
        "validate_ast": "Validate an expression AST against selected resources and type rules.",
        "search_reference_node": "Search existing tree nodes that can serve as expression references.",
    }.items():
        registries.tools.register(
            ToolDefinition(
                name=name,
                description=description,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                concurrency_safe=True,
                execute=tool_callables.get(name, _missing_tool(name)),
            )
        )


def _register_expression_skills(registries: CapabilityRegistries) -> None:
    registries.skills.register(
        SkillDefinition(
            name="resource_search",
            description="Select the minimal resource set required to generate an expression.",
            instruction=(
                "Use the query, target node, generated spec, and previous observations to select "
                "only relevant context, BO, naming SQL, and reference-node resources."
            ),
            applicable_workflows=(EXPRESSION_WORKFLOW_NAME,),
            applicable_stages=("resource_search",),
            allowed_tools=(
                "search_context",
                "search_bo",
                "search_namingsql",
                "search_reference_node",
                "inspect_return_type",
            ),
            knowledge_requirements=(
                "expression.resource-model",
                "expression.context",
                "expression.bo",
                "expression.naming-sql",
                "expression.return-type",
            ),
        )
    )
    registries.skills.register(
        SkillDefinition(
            name="expression_generation",
            description="Generate expression plans and ASTs from selected resources.",
            instruction=(
                "Build the expression from the selected resources and available type/method "
                "information; prefer explicit resource evidence over broad global context."
            ),
            applicable_workflows=(EXPRESSION_WORKFLOW_NAME,),
            applicable_stages=("expression_generate", "finalize"),
            allowed_tools=("inspect_return_type",),
            knowledge_requirements=(
                "expression.resource-model",
                "expression.return-type",
                "expression.ast",
            ),
        )
    )
    registries.skills.register(
        SkillDefinition(
            name="expression_repair",
            description="Repair failed expressions using validation errors and prior observations.",
            instruction=(
                "Use validation errors, execution history, selected resource metadata, and type "
                "rules to make the smallest repair that preserves the original goal."
            ),
            applicable_workflows=(EXPRESSION_WORKFLOW_NAME,),
            applicable_stages=("ast_validation", "expression_generate"),
            allowed_tools=("validate_ast", "inspect_return_type"),
            knowledge_requirements=(
                "expression.return-type",
                "expression.ast",
            ),
        )
    )


def _register_expression_knowledge(registries: CapabilityRegistries) -> None:
    for definition in (
        KnowledgeDefinition(
            knowledge_id="expression.resource-model",
            title="Expression Resource Model",
            scope="expression",
            workflow=EXPRESSION_WORKFLOW_NAME,
            stage=None,
            tags=("resource", "context", "bo", "namingsql"),
            priority=90,
            source_path=_KNOWLEDGE_ROOT / "resource-model.md",
        ),
        KnowledgeDefinition(
            knowledge_id="expression.context",
            title="Expression Context Rules",
            scope="expression",
            workflow=EXPRESSION_WORKFLOW_NAME,
            stage="resource_search",
            tags=("context", "resource"),
            priority=80,
            source_path=_KNOWLEDGE_ROOT / "context.md",
        ),
        KnowledgeDefinition(
            knowledge_id="expression.bo",
            title="Expression BO Rules",
            scope="expression",
            workflow=EXPRESSION_WORKFLOW_NAME,
            stage="resource_search",
            tags=("bo", "resource"),
            priority=80,
            source_path=_KNOWLEDGE_ROOT / "bo.md",
        ),
        KnowledgeDefinition(
            knowledge_id="expression.naming-sql",
            title="Expression Naming SQL Rules",
            scope="expression",
            workflow=EXPRESSION_WORKFLOW_NAME,
            stage="resource_search",
            tags=("namingsql", "sql", "resource"),
            priority=80,
            source_path=_KNOWLEDGE_ROOT / "naming-sql.md",
        ),
        KnowledgeDefinition(
            knowledge_id="expression.return-type",
            title="Expression Return Type Rules",
            scope="expression",
            workflow=EXPRESSION_WORKFLOW_NAME,
            stage=None,
            tags=("return-type", "type"),
            priority=70,
            source_path=_KNOWLEDGE_ROOT / "return-type.md",
        ),
        KnowledgeDefinition(
            knowledge_id="expression.ast",
            title="Expression AST Rules",
            scope="expression",
            workflow=EXPRESSION_WORKFLOW_NAME,
            stage=None,
            tags=("ast", "validation", "generation"),
            priority=70,
            source_path=_KNOWLEDGE_ROOT / "ast.md",
        ),
    ):
        registries.knowledge.register(definition)


def _missing_tool(name: str) -> Callable[..., Any]:
    def execute(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(f"tool implementation is not bound: {name}")

    return execute
