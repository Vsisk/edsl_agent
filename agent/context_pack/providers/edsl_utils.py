import hashlib
import json
from typing import Any

from jsonpath_ng import parse

from agent.context_pack.indexing.edsl_tree import EdslIndexEntry
from agent.context_pack.models import (ContextFact, ContextItem, ResourceName, SearchDocument,
                                       SourceLocator)


def resolve_json_path(tree: dict[str, Any], json_path: str) -> Any | None:
    matches = parse(json_path).find(tree)
    return matches[0].value if len(matches) == 1 else None


def entry_content(entry: EdslIndexEntry, canonical: Any) -> dict[str, Any]:
    return {
        "name": entry.name,
        "annotation": entry.annotation,
        "data_type": entry.data_type,
        "tree_node_type": entry.tree_node_type,
        "field_role": entry.field_role,
        "json_path": entry.json_path,
        "xml_path": entry.xml_path,
        "value": canonical if isinstance(canonical, dict) else entry.content,
    }


def entry_document(entry: EdslIndexEntry, tree: dict[str, Any], source_version: str) -> SearchDocument | None:
    canonical = resolve_json_path(tree, entry.json_path)
    if canonical is None:
        return None
    content = entry_content(entry, canonical)
    content_hash = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    facts = []
    if entry.name and entry.data_type:
        facts.append(ContextFact(key=f"field.{entry.name}.type", value=entry.data_type))
    return SearchDocument(
        item_id=entry.item_id,
        source_id=entry.source_id,
        item_type=entry.item_type,
        search_text=entry.search_text,
        summary=" / ".join(value for value in (entry.name, entry.annotation, entry.xml_path) if value),
        locator=SourceLocator(
            source_id=entry.source_id,
            kind="json_path",
            value=entry.json_path,
            source_version=source_version,
        ),
        authority="authoritative" if entry.source_id == "current-tree" else "reference",
        content_hash=content_hash,
        content=content,
        facts=facts,
    )


def hit_item(hit, resource_name: ResourceName, tree: dict[str, Any]) -> ContextItem | None:
    if resolve_json_path(tree, hit.document.locator.value) is None:
        return None
    return ContextItem(
        item_id=hit.document.item_id,
        resource_name=resource_name,
        item_type=hit.document.item_type,
        authority=hit.document.authority,
        content=hit.document.content,
        summary=hit.document.summary,
        locator=hit.document.locator,
        evidence=hit.evidence,
        content_hash=hit.document.content_hash,
        facts=hit.document.facts,
        rank=hit.rank,
    )
