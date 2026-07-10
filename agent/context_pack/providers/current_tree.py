from agent.context_pack.indexing.edsl_tree import EdslIndexBuilder
from agent.context_pack.models import (BudgetUsage, ContextPackRequest, ContextSection,
                                       ContextWarning, ResourceName, SectionStatus)
from agent.context_pack.project_context import ProjectContext
from agent.context_pack.registry import RecallProfile
from agent.context_pack.search import LocalResourceSearchTool
from agent.resource_manager.loader.local_context_loader import load_visible_local_context_registry

from .edsl_utils import entry_document, hit_item


class CurrentTreeProvider:
    resource_name = ResourceName.CURRENT_TREE
    source_id = "current-tree"

    def __init__(self, search_tool: LocalResourceSearchTool, index_builder: EdslIndexBuilder | None = None) -> None:
        self.search_tool = search_tool
        self.index_builder = index_builder or EdslIndexBuilder()

    def retrieve(self, request: ContextPackRequest, project_context: ProjectContext,
                 profile: RecallProfile) -> ContextSection:
        tree = project_context.current_tree
        if not tree:
            return ContextSection(resource_name=self.resource_name, status=SectionStatus.UNAVAILABLE)
        entries = self.index_builder.build(tree, self.source_id)
        node_id = str(request.node.get("node_id") or "")
        current = next((entry for entry in entries if entry.node_id == node_id and entry.item_type in {"node", "field"}), None)
        if current is None:
            return ContextSection(
                resource_name=self.resource_name,
                status=SectionStatus.ERROR,
                warnings=[ContextWarning(code="CURRENT_NODE_NOT_FOUND", message=node_id)],
            )
        visible = load_visible_local_context_registry(tree, current.json_path)
        allowed_paths = {item.source_path for item in visible}
        filtered = [
            entry for entry in entries
            if entry.item_type not in {"local", "iter"} or entry.json_path in allowed_paths
        ]
        version = project_context.source_versions.get(self.source_id, "request-snapshot")
        documents = [doc for entry in filtered if (doc := entry_document(entry, tree, version)) is not None]
        self.search_tool.register_source(self.source_id, documents)
        query = " ".join(str(value or "") for value in (
            request.query, request.node.get("name"), request.node.get("annotation"), request.node.get("tree_node_type")
        ))
        result = self.search_tool.search(self.source_id, query, limit=profile.max_items)
        items = [item for hit in result.hits if (item := hit_item(hit, self.resource_name, tree)) is not None]
        status = SectionStatus.DEGRADED if result.degraded and items else SectionStatus.READY if items else SectionStatus.EMPTY
        return ContextSection(
            resource_name=self.resource_name,
            status=status,
            items=items,
            budget_usage=BudgetUsage(
                item_count=len(items), character_count=sum(len(str(item.content)) for item in items)
            ),
            metadata={"current_json_path": current.json_path, "source_version": version},
        )
