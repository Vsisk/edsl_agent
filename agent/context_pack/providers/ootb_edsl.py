import hashlib
import json
from copy import deepcopy
from typing import Any

from agent.context_pack.indexing.edsl_tree import EdslIndexBuilder
from agent.context_pack.models import (BudgetUsage, ContextPackRequest, ContextSection,
                                       ResourceName, SectionStatus)
from agent.context_pack.project_context import ProjectContext
from agent.context_pack.registry import RecallProfile
from agent.context_pack.search import LocalResourceSearchTool

from .edsl_utils import entry_document, hit_item


def _bounded_value(value: Any, *, depth: int = 0, max_depth: int = 2, max_children: int = 8) -> Any:
    if depth >= max_depth:
        if isinstance(value, (dict, list)):
            return {"truncated": True} if isinstance(value, dict) else ["<truncated>"]
        return value
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key == "children" and isinstance(child, list):
                result[key] = [_bounded_value(item, depth=depth + 1, max_depth=max_depth, max_children=max_children) for item in child[:max_children]]
                if len(child) > max_children:
                    result["children_truncated"] = len(child) - max_children
            else:
                result[key] = _bounded_value(child, depth=depth + 1, max_depth=max_depth, max_children=max_children)
        return result
    if isinstance(value, list):
        return [_bounded_value(item, depth=depth + 1, max_depth=max_depth, max_children=max_children) for item in value[:max_children]]
    return deepcopy(value)


class OotbEdslProvider:
    resource_name = ResourceName.OOTB_EDSL
    source_id = "ootb-edsl"

    def __init__(self, search_tool: LocalResourceSearchTool, index_builder: EdslIndexBuilder | None = None) -> None:
        self.search_tool = search_tool
        self.index_builder = index_builder or EdslIndexBuilder()

    def retrieve(self, request: ContextPackRequest, project_context: ProjectContext,
                 profile: RecallProfile) -> ContextSection:
        tree = project_context.ootb_tree
        if not tree:
            return ContextSection(resource_name=self.resource_name, status=SectionStatus.UNAVAILABLE)
        expected_type = str(request.node.get("tree_node_type") or "")
        entries = self.index_builder.build(tree, self.source_id)
        compatible = [entry for entry in entries if expected_type and entry.tree_node_type == expected_type]
        if not compatible:
            return ContextSection(resource_name=self.resource_name, status=SectionStatus.EMPTY)
        version = project_context.source_versions.get(self.source_id, "ootb-snapshot")
        documents = []
        for entry in compatible:
            document = entry_document(entry, tree, version)
            if document is None:
                continue
            content = dict(document.content)
            content["value"] = _bounded_value(content.get("value"))
            content_hash = hashlib.sha256(
                json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            documents.append(document.model_copy(update={"content": content, "content_hash": content_hash}))
        self.search_tool.register_source(self.source_id, documents)
        query = " ".join(str(value or "") for value in (
            request.query, request.node.get("name"), request.node.get("annotation")
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
            metadata={"source_version": version, "expected_node_type": expected_type},
        )
