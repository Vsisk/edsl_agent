from pathlib import Path

from agent.context_pack.indexing.markdown_skill import MarkdownSkillParser
from agent.context_pack.models import (BudgetUsage, ContextItem, ContextPackRequest,
                                       ContextSection, ResourceName, SectionStatus)
from agent.context_pack.project_context import ProjectContext
from agent.context_pack.registry import RecallProfile
from agent.context_pack.search import LocalResourceSearchTool


class DevSkillProvider:
    resource_name = ResourceName.DEV_SKILL
    source_id = "dev-skill"

    def __init__(self, search_tool: LocalResourceSearchTool, parser: MarkdownSkillParser | None = None) -> None:
        self.search_tool = search_tool
        self.parser = parser or MarkdownSkillParser()

    def retrieve(
        self,
        request: ContextPackRequest,
        project_context: ProjectContext,
        profile: RecallProfile,
    ) -> ContextSection:
        path = project_context.dev_skill_path
        if path is None or not Path(path).is_file():
            return ContextSection(resource_name=self.resource_name, status=SectionStatus.UNAVAILABLE)
        path = Path(path)
        documents = self.parser.parse(path, self.source_id)
        self.search_tool.register_source(self.source_id, documents, root=path.parent)
        node_text = " ".join(str(request.node.get(key) or "") for key in ("name", "annotation", "tree_node_type"))
        result = self.search_tool.search(
            self.source_id,
            f"{request.query} {node_text}",
            limit=profile.max_items,
        )
        items = []
        for hit in result.hits:
            markdown = self.search_tool.read_slice(hit.document.locator, hit.document.content_hash)
            content = dict(hit.document.content)
            content["markdown"] = markdown
            items.append(ContextItem(
                item_id=hit.document.item_id,
                resource_name=self.resource_name,
                item_type=hit.document.item_type,
                authority=hit.document.authority,
                content=content,
                summary=hit.document.summary,
                locator=hit.document.locator,
                evidence=hit.evidence,
                content_hash=hit.document.content_hash,
                facts=hit.document.facts,
                rank=hit.rank,
            ))
        if items:
            status = SectionStatus.DEGRADED if result.degraded else SectionStatus.READY
        else:
            status = SectionStatus.EMPTY
        return ContextSection(
            resource_name=self.resource_name,
            status=status,
            items=items,
            budget_usage=BudgetUsage(
                item_count=len(items),
                character_count=sum(len(item.content.get("markdown", "")) for item in items),
            ),
            metadata={"source_path": str(path)},
        )
