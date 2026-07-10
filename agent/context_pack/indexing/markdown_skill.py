from __future__ import annotations

import hashlib
import re
from pathlib import Path

from markdown_it import MarkdownIt

from agent.context_pack.models import SearchDocument, SourceLocator


class MarkdownSkillParser:
    parser_version = "markdown-skill-v1"

    def parse(self, path: str | Path, source_id: str) -> list[SearchDocument]:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        tokens = MarkdownIt("commonmark").parse(text)
        headings: list[tuple[int, str, int]] = []
        for index, token in enumerate(tokens):
            if token.type != "heading_open" or token.map is None:
                continue
            level = int(token.tag[1:])
            title = tokens[index + 1].content.strip()
            headings.append((level, title, token.map[0]))
        documents = []
        for position, (level, title, start) in enumerate(headings):
            if level not in (2, 3):
                continue
            if level == 2 and any(next_level == 3 for next_level, _, _ in self._until_peer(headings, position, 2)):
                continue
            end = len(lines)
            for next_level, _, next_start in headings[position + 1:]:
                if next_level <= level:
                    end = next_start
                    break
            heading_path = self._heading_path(headings, position)
            markdown = "".join(lines[start:end])
            content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            item_id = "skill:" + hashlib.sha256(
                f"{source_id}|{'/'.join(heading_path)}".encode("utf-8")
            ).hexdigest()[:20]
            search_text = re.sub(r"[`#*_>-]+", " ", f"{' '.join(heading_path)} {markdown}")
            documents.append(SearchDocument(
                item_id=item_id,
                source_id=source_id,
                item_type="knowledge_recipe",
                search_text=search_text,
                summary=" / ".join(heading_path),
                locator=SourceLocator(
                    source_id=source_id,
                    kind="line_range",
                    value=" / ".join(heading_path),
                    path=path.name,
                    start_line=start + 1,
                    end_line=end,
                ),
                authority="normative",
                content_hash=content_hash,
                content={"heading_path": heading_path, "markdown": markdown},
            ))
        return documents

    @staticmethod
    def _until_peer(headings, position, level):
        result = []
        for heading in headings[position + 1:]:
            if heading[0] <= level:
                break
            result.append(heading)
        return result

    @staticmethod
    def _heading_path(headings, position):
        level, title, _ = headings[position]
        parents = []
        expected = level - 1
        for parent_level, parent_title, _ in reversed(headings[:position]):
            if parent_level == expected:
                parents.append(parent_title)
                expected -= 1
            if expected == 0:
                break
        return [*reversed(parents), title]
