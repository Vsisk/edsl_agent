from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    concurrency_safe: bool
    execute: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    description: str
    instruction: str
    applicable_workflows: tuple[str, ...] = ()
    applicable_stages: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    knowledge_requirements: tuple[str, ...] = ()

    def applies_to(self, *, workflow: str | None, stage: str | None) -> bool:
        workflow_matches = not self.applicable_workflows or workflow in self.applicable_workflows
        stage_matches = not self.applicable_stages or stage in self.applicable_stages
        return workflow_matches and stage_matches


@dataclass(frozen=True, slots=True)
class KnowledgeDefinition:
    knowledge_id: str
    title: str
    scope: str
    workflow: str | None = None
    stage: str | None = None
    tags: tuple[str, ...] = ()
    priority: int = 0
    source_path: Path | str | None = None

    def normalized_source_path(self) -> Path | None:
        if self.source_path is None:
            return None
        return Path(self.source_path)

    def matches(
        self,
        *,
        workflow: str | None = None,
        stage: str | None = None,
        scope: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> bool:
        if workflow is not None and self.workflow not in (None, workflow):
            return False
        if stage is not None and self.stage not in (None, stage):
            return False
        if scope is not None and self.scope != scope:
            return False
        if tags and not set(tags).intersection(self.tags):
            return False
        return True


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    definition: KnowledgeDefinition
    content: str


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        return self._tools[name]

    def select(self, names: tuple[str, ...] | list[str]) -> dict[str, ToolDefinition]:
        return {name: self.get(name) for name in names}

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, definition: SkillDefinition) -> None:
        if definition.name in self._skills:
            raise ValueError(f"skill already registered: {definition.name}")
        self._skills[definition.name] = definition

    def get(self, name: str) -> SkillDefinition:
        return self._skills[name]

    def select(
        self,
        *,
        names: tuple[str, ...] | list[str] = (),
        workflow: str | None = None,
        stage: str | None = None,
    ) -> list[SkillDefinition]:
        candidates = [self.get(name) for name in names] if names else self.list()
        return [
            skill
            for skill in candidates
            if skill.applies_to(workflow=workflow, stage=stage)
        ]

    def list(self) -> list[SkillDefinition]:
        return list(self._skills.values())


class KnowledgeRegistry:
    def __init__(self) -> None:
        self._knowledge: dict[str, KnowledgeDefinition] = {}

    def register(self, definition: KnowledgeDefinition) -> None:
        if definition.knowledge_id in self._knowledge:
            raise ValueError(f"knowledge already registered: {definition.knowledge_id}")
        self._knowledge[definition.knowledge_id] = definition

    def get(self, knowledge_id: str) -> KnowledgeDefinition:
        return self._knowledge[knowledge_id]

    def search(
        self,
        *,
        knowledge_ids: tuple[str, ...] | list[str] = (),
        workflow: str | None = None,
        stage: str | None = None,
        scope: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
    ) -> list[KnowledgeDefinition]:
        if knowledge_ids:
            candidates = [self.get(knowledge_id) for knowledge_id in knowledge_ids]
        else:
            candidates = list(self._knowledge.values())
        selected = [
            definition
            for definition in candidates
            if definition.matches(
                workflow=workflow,
                stage=stage,
                scope=scope,
                tags=tuple(tags),
            )
        ]
        deduped: dict[str, KnowledgeDefinition] = {}
        for definition in selected:
            deduped.setdefault(definition.knowledge_id, definition)
        return sorted(
            deduped.values(),
            key=lambda definition: (-definition.priority, definition.knowledge_id),
        )

    def load(
        self,
        *,
        knowledge_ids: tuple[str, ...] | list[str] = (),
        workflow: str | None = None,
        stage: str | None = None,
        scope: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
    ) -> list[KnowledgeDocument]:
        return [
            KnowledgeDocument(definition=definition, content=self._read(definition))
            for definition in self.search(
                knowledge_ids=knowledge_ids,
                workflow=workflow,
                stage=stage,
                scope=scope,
                tags=tags,
            )
        ]

    def list(self) -> list[KnowledgeDefinition]:
        return list(self._knowledge.values())

    def _read(self, definition: KnowledgeDefinition) -> str:
        source_path = definition.normalized_source_path()
        if source_path is None:
            return ""
        return source_path.read_text(encoding="utf-8")


@dataclass(slots=True)
class CapabilityRegistries:
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    skills: SkillRegistry = field(default_factory=SkillRegistry)
    knowledge: KnowledgeRegistry = field(default_factory=KnowledgeRegistry)
