from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from agent.context_pack.models import ContextPack
from agent.models import NodeDef, ValueLogicRequest
from agent.resource_manager.loader.local_context_loader import (
    load_visible_local_context_registry,
)


DEFAULT_EXPRESSION_SKILL_PATH = (
    Path(__file__).resolve().parent / "resources" / "expression_skill.md"
)


@dataclass(slots=True)
class ExpressionScopeContext:
    inside_parent_list: bool = False
    parent_list_path: str | None = None
    iter_path: str | None = None
    iter_return_type: dict[str, Any] | None = None


@dataclass(slots=True)
class ExpressionSkillInstruction:
    skill_id: str
    title: str
    markdown: str


@dataclass(slots=True)
class ExpressionSpec:
    nl: str
    scope_context: ExpressionScopeContext = field(
        default_factory=ExpressionScopeContext
    )
    skill_instructions: list[ExpressionSkillInstruction] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class _ExpressionSkillSection:
    skill_id: str
    title: str
    triggers: tuple[str, ...]
    markdown: str


class ExpressionSkillLibrary:
    def __init__(self, path: str | Path = DEFAULT_EXPRESSION_SKILL_PATH) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"expression skill file not found: {self.path}")
        self.sections = self._parse(self.path.read_text(encoding="utf-8"))

    def recall(
        self,
        *,
        text: str,
        inside_parent_list: bool,
    ) -> list[ExpressionSkillInstruction]:
        normalized = " ".join(str(text or "").lower().split())
        result: list[ExpressionSkillInstruction] = []
        for section in self.sections:
            structural_match = (
                inside_parent_list
                and "structural:parent_list" in section.triggers
            )
            lexical_match = any(
                trigger != "structural:parent_list" and trigger in normalized
                for trigger in section.triggers
            )
            if structural_match or lexical_match:
                result.append(
                    ExpressionSkillInstruction(
                        skill_id=section.skill_id,
                        title=section.title,
                        markdown=section.markdown,
                    )
                )
        return result

    @staticmethod
    def _parse(text: str) -> list[_ExpressionSkillSection]:
        lines = text.splitlines(keepends=True)
        headings = [
            (index, match.group(1).strip())
            for index, line in enumerate(lines)
            if (match := re.match(r"^##\s+(.+?)\s*$", line))
        ]
        result: list[_ExpressionSkillSection] = []
        for position, (start, title) in enumerate(headings):
            end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
            markdown = "".join(lines[start:end]).strip()
            skill_id = _metadata_value(markdown, "skill_id")
            trigger_text = _metadata_value(markdown, "triggers")
            if not skill_id or not trigger_text:
                raise ValueError(f"invalid expression skill section: {title}")
            triggers = tuple(
                trigger.strip().lower()
                for trigger in trigger_text.split(",")
                if trigger.strip()
            )
            result.append(
                _ExpressionSkillSection(
                    skill_id=skill_id,
                    title=title,
                    triggers=triggers,
                    markdown=markdown,
                )
            )
        if not result:
            raise ValueError("expression skill file contains no H2 sections")
        return result


class ExpressionSpecGenerator:
    def __init__(self, skill_library: ExpressionSkillLibrary | None = None) -> None:
        self.skill_library = skill_library or ExpressionSkillLibrary()

    def generate(
        self,
        *,
        request: ValueLogicRequest,
        node_info: NodeDef,
        context_pack: ContextPack | None = None,
        retry_feedback: dict[str, Any] | None = None,
    ) -> ExpressionSpec:
        del context_pack, retry_feedback
        visible = load_visible_local_context_registry(
            request.edsl_tree or {},
            request.node_path,
        )
        iterator = next(
            (item for item in visible if item.context_name == "$iter$"),
            None,
        )
        scope = ExpressionScopeContext()
        if iterator is not None and iterator.return_type is not None:
            scope = ExpressionScopeContext(
                inside_parent_list=True,
                parent_list_path=_parent_list_path(iterator.source_path),
                iter_path=iterator.context_name,
                iter_return_type=iterator.return_type.model_dump(mode="json"),
            )
        nl = str(request.query or "").strip()
        recall_text = " ".join(
            value
            for value in (
                nl,
                node_info.node_name,
                node_info.description,
            )
            if value
        )
        return ExpressionSpec(
            nl=nl,
            scope_context=scope,
            skill_instructions=self.skill_library.recall(
                text=recall_text,
                inside_parent_list=scope.inside_parent_list,
            ),
        )


def _metadata_value(markdown: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.+?)\s*$", markdown)
    return match.group(1).strip() if match else ""


def _parent_list_path(source_path: str) -> str | None:
    suffix = ".data_source"
    return source_path[: -len(suffix)] if source_path.endswith(suffix) else None
