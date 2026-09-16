from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from typing import Any

from agent.workflow.capabilities import (
    CapabilityRegistries,
    KnowledgeDocument,
    SkillDefinition,
    ToolDefinition,
)
from agent.workflow.core import Stage, WorkflowDefinition, WorkflowRunState


@dataclass(frozen=True, slots=True)
class HarnessContext:
    session: Any | None = None
    site_id: str | None = None
    project_id: str | None = None
    project_ref: Any | None = None
    conversation_ref: Any | None = None
    task_ref: Any | None = None
    resource_version: str | None = None
    capability_registries: CapabilityRegistries | None = None
    facts: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_environment(cls, environment: Any) -> "HarnessContext":
        if isinstance(environment, cls):
            return environment
        facts = {
            name: getattr(environment, name)
            for name in dir(environment)
            if not name.startswith("_") and not callable(getattr(environment, name))
        }
        facts["environment"] = environment
        request = facts.get("request")
        return cls(
            site_id=getattr(request, "site_id", None),
            project_id=getattr(request, "project_id", None),
            capability_registries=facts.get("capability_registries"),
            facts=facts,
        )

    def require_fact(self, key: str) -> Any:
        if key not in self.facts:
            raise KeyError(f"harness fact not found: {key}")
        return self.facts[key]

    def get_fact(self, key: str, default: Any = None) -> Any:
        return self.facts.get(key, default)


@dataclass(frozen=True, slots=True)
class WorkflowContext:
    harness_context: HarnessContext
    workflow_name: str
    current_goal: Any | None
    workflow_input: dict[str, Any]
    artifacts: dict[str, Any]
    observations: dict[str, Any]
    execution_history_summary: list[dict[str, Any]]
    downstream_feedback: dict[str, Any]

    @classmethod
    def from_state(
        cls,
        *,
        harness_context: HarnessContext,
        workflow_state: WorkflowRunState,
    ) -> "WorkflowContext":
        return cls(
            harness_context=harness_context,
            workflow_name=workflow_state.workflow_name,
            current_goal=workflow_state.workflow_input.get("goal"),
            workflow_input=workflow_state.workflow_input,
            artifacts=workflow_state.artifacts,
            observations=workflow_state.observations,
            execution_history_summary=list(workflow_state.stage_trace),
            downstream_feedback=_build_downstream_feedback(workflow_state),
        )


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    input_model: type
    workflow_input_bindings: dict[str, str] = field(default_factory=dict)
    artifact_bindings: dict[str, str] = field(default_factory=dict)
    optional_artifact_bindings: dict[str, str] = field(default_factory=dict)
    harness_bindings: dict[str, str] = field(default_factory=dict)
    optional_harness_bindings: dict[str, str] = field(default_factory=dict)
    observation_bindings: dict[str, str] = field(default_factory=dict)
    include_execution_history_summary: bool = False
    downstream_feedback_field: str | None = None
    tool_names: tuple[str, ...] = ()
    skill_names: tuple[str, ...] = ()
    knowledge_ids: tuple[str, ...] = ()
    knowledge_tags: tuple[str, ...] = ()
    knowledge_scope: str | None = None
    inject_capabilities: bool = False


@dataclass(frozen=True, slots=True)
class StageCapabilities:
    tools: dict[str, ToolDefinition] = field(default_factory=dict)
    skills: list[SkillDefinition] = field(default_factory=list)
    knowledge: list[KnowledgeDocument] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StageContext:
    stage_name: str
    input_model: type
    values: dict[str, Any]
    workflow_context: WorkflowContext
    capabilities: StageCapabilities = field(default_factory=StageCapabilities)

    def to_stage_input(self) -> Any:
        return self.input_model(**self.values)


class ContextAssembler:
    def build(
        self,
        harness_context: HarnessContext | Any,
        workflow_definition: WorkflowDefinition,
        workflow_state: WorkflowRunState,
        stage: Stage,
    ) -> StageContext:
        normalized_harness = HarnessContext.from_environment(harness_context)
        workflow_context = WorkflowContext.from_state(
            harness_context=normalized_harness,
            workflow_state=workflow_state,
        )
        policy = self._policy_for(stage)
        values: dict[str, Any] = {}

        for input_name, key in policy.workflow_input_bindings.items():
            values[input_name] = workflow_context.workflow_input[key]
        for input_name, key in policy.artifact_bindings.items():
            values[input_name] = workflow_state.require_artifact(key)
        for input_name, key in policy.optional_artifact_bindings.items():
            if workflow_state.has_artifact(key):
                values[input_name] = workflow_state.require_artifact(key)
        for input_name, key in policy.harness_bindings.items():
            values[input_name] = self._read_harness_value(normalized_harness, key)
        for input_name, key in policy.optional_harness_bindings.items():
            if self._has_harness_value(normalized_harness, key):
                values[input_name] = self._read_harness_value(normalized_harness, key)
        for input_name, key in policy.observation_bindings.items():
            values[input_name] = workflow_context.observations[key]
        if policy.include_execution_history_summary:
            values["execution_history_summary"] = workflow_context.execution_history_summary
        if (
            policy.downstream_feedback_field is not None
            and policy.downstream_feedback_field in self._input_model_fields(policy.input_model)
        ):
            values[policy.downstream_feedback_field] = workflow_context.downstream_feedback
        capabilities = self._assemble_capabilities(
            policy=policy,
            harness_context=normalized_harness,
            workflow_definition=workflow_definition,
            stage=stage,
        )
        if policy.inject_capabilities:
            self._inject_capability_values(
                values=values,
                input_model=policy.input_model,
                capabilities=capabilities,
            )

        return StageContext(
            stage_name=stage.name,
            input_model=policy.input_model,
            values=values,
            workflow_context=workflow_context,
            capabilities=capabilities,
        )

    def _policy_for(self, stage: Stage) -> ContextPolicy:
        policy = getattr(stage, "context_policy", None)
        if policy is not None:
            return policy
        return ContextPolicy(
            input_model=stage.input_model,
            artifact_bindings=getattr(stage, "artifact_bindings", {}),
            optional_artifact_bindings=getattr(stage, "optional_artifact_bindings", {}),
            harness_bindings=getattr(stage, "environment_bindings", {}),
        )

    def _has_harness_value(self, harness_context: HarnessContext, key: str) -> bool:
        return hasattr(harness_context, key) or key in harness_context.facts

    def _read_harness_value(self, harness_context: HarnessContext, key: str) -> Any:
        if hasattr(harness_context, key):
            return getattr(harness_context, key)
        return harness_context.require_fact(key)

    def _assemble_capabilities(
        self,
        *,
        policy: ContextPolicy,
        harness_context: HarnessContext,
        workflow_definition: WorkflowDefinition,
        stage: Stage,
    ) -> StageCapabilities:
        registries = harness_context.capability_registries
        if registries is None:
            registries = harness_context.get_fact("capability_registries")
        if registries is None:
            return StageCapabilities()

        tools = registries.tools.select(policy.tool_names) if policy.tool_names else {}
        skills = registries.skills.select(
            names=policy.skill_names,
            workflow=workflow_definition.name,
            stage=stage.name,
        )
        knowledge_ids = list(policy.knowledge_ids)
        for skill in skills:
            knowledge_ids.extend(skill.knowledge_requirements)
        knowledge: list[KnowledgeDocument] = []
        if knowledge_ids:
            knowledge.extend(
                registries.knowledge.load(
                    knowledge_ids=tuple(dict.fromkeys(knowledge_ids)),
                    workflow=workflow_definition.name,
                    stage=stage.name,
                    scope=policy.knowledge_scope,
                )
            )
        if policy.knowledge_tags:
            knowledge.extend(
                registries.knowledge.load(
                    workflow=workflow_definition.name,
                    stage=stage.name,
                    scope=policy.knowledge_scope,
                    tags=policy.knowledge_tags,
                )
            )
        deduped_knowledge = {
            document.definition.knowledge_id: document for document in knowledge
        }
        return StageCapabilities(
            tools=tools,
            skills=skills,
            knowledge=sorted(
                deduped_knowledge.values(),
                key=lambda document: (
                    -document.definition.priority,
                    document.definition.knowledge_id,
                ),
            ),
        )

    def _inject_capability_values(
        self,
        *,
        values: dict[str, Any],
        input_model: type,
        capabilities: StageCapabilities,
    ) -> None:
        accepted_fields = set(self._input_model_fields(input_model))
        if "tools" in accepted_fields:
            values["tools"] = capabilities.tools
        if "skills" in accepted_fields:
            values["skills"] = capabilities.skills
        if "knowledge" in accepted_fields:
            values["knowledge"] = capabilities.knowledge

    def _input_model_fields(self, input_model: type) -> tuple[str, ...]:
        model_fields = getattr(input_model, "model_fields", None)
        if isinstance(model_fields, dict):
            return tuple(model_fields)
        dataclass_fields = getattr(input_model, "__dataclass_fields__", None)
        if isinstance(dataclass_fields, dict):
            return tuple(dataclass_fields)
        try:
            signature = inspect.signature(input_model)
        except (TypeError, ValueError):
            return ()
        return tuple(signature.parameters)


def _build_downstream_feedback(workflow_state: WorkflowRunState) -> dict[str, Any]:
    latest_observation = _latest_observation(workflow_state)
    validation = workflow_state.artifacts.get("validation")
    feedback = {
        "previous_selected_resources": workflow_state.artifacts.get("resources")
        or workflow_state.artifacts.get("selected_resources"),
        "previous_candidates": workflow_state.artifacts.get("resource_candidates")
        or workflow_state.artifacts.get("candidates"),
        "generated_expression": workflow_state.artifacts.get("final_expression")
        or workflow_state.artifacts.get("expression")
        or workflow_state.artifacts.get("ast"),
        "validation_error": latest_observation.to_dict()
        if hasattr(latest_observation, "to_dict")
        else latest_observation,
        "missing_information": getattr(latest_observation, "missing_information", []),
        "missing_property": _first_missing(latest_observation, "property"),
        "missing_type": _first_missing(latest_observation, "type"),
        "rejected_resource_ids": workflow_state.artifacts.get("rejected_resource_ids", []),
        "execution_history_summary": list(workflow_state.stage_trace),
    }
    if validation is not None:
        feedback["validation_result"] = validation
    return feedback


def _latest_observation(workflow_state: WorkflowRunState) -> Any | None:
    for item in reversed(workflow_state.stage_trace):
        stage = item.get("stage")
        if stage in workflow_state.observations:
            return workflow_state.observations[stage]
    if workflow_state.observations:
        return next(reversed(workflow_state.observations.values()))
    return None


def _first_missing(observation: Any | None, marker: str) -> str | None:
    if observation is None:
        return None
    for item in getattr(observation, "missing_information", []) or []:
        text = str(item)
        if text.startswith(f"{marker}:"):
            return text.split(":", 1)[1]
        if marker in text.lower():
            return text
    evidence = getattr(observation, "evidence", {}) or {}
    if isinstance(evidence, dict):
        for key in (marker, f"{marker}_name", f"missing_{marker}"):
            if evidence.get(key) is not None:
                return str(evidence[key])
    return None
