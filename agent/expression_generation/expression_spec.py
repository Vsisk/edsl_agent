from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

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


def _metadata_value(markdown: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.+?)\s*$", markdown)
    return match.group(1).strip() if match else ""
