from __future__ import annotations

import json
from typing import Any

from .models import NodeIndexEntry


def _xml_name(node: dict[str, Any]) -> str | None:
    value = node.get("xml_name_property", {}).get("xml_name")
    return str(value) if value not in (None, "") else None


def _context_names(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("name", "variable_name", "xml_name", "key"):
            if item.get(key):
                names.append(str(item[key]))
                break
    return names


class NodeIndexBuilder:
    """Build a compact, searchable DFS index without exposing the tree to an LLM."""

    def build(self, tree_json: dict[str, Any]) -> list[NodeIndexEntry]:
        if not isinstance(tree_json, dict) or not tree_json:
            raise ValueError("tree_json must be a non-empty object")
        has_mapping = isinstance(tree_json.get("mapping_content"), dict)
        root = tree_json["mapping_content"] if has_mapping else tree_json
        root_path = "$.mapping_content" if has_mapping else "$"
        result: list[NodeIndexEntry] = []

        def visit(
            node: dict[str, Any],
            json_path: str,
            parent: NodeIndexEntry | None,
            ancestors: list[str],
        ) -> None:
            name = _xml_name(node)
            current_names = [*ancestors, name] if name else list(ancestors)
            children = node.get("children") if isinstance(node.get("children"), list) else []
            semi_text: list[str] = []
            nl_items = node.get("edsl_semi_struct", {}).get("nl", [])
            if isinstance(nl_items, list):
                for item in nl_items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("nl"):
                        semi_text.append(str(item["nl"]))
                    terms = item.get("cbs_terms", [])
                    if isinstance(terms, list):
                        semi_text.extend(str(term) for term in terms if term)
                    elif terms:
                        semi_text.append(str(terms))
            data_source = node.get("data_source")
            ab_source = node.get("ab_content", {}).get("data_source")
            source = ab_source if isinstance(ab_source, dict) else data_source
            source_summary = None
            if isinstance(source, dict):
                source_summary = " ".join(
                    str(source[key]) for key in ("data_source_type", "name", "description") if source.get(key)
                ) or json.dumps(source, ensure_ascii=False, default=str)[:300]
            ab_bo_name = None
            if isinstance(ab_source, dict) and ab_source.get("data_source_type") == "sql":
                value = ab_source.get("sql_query", {}).get("bo_name")
                ab_bo_name = str(value) if value else None
            child_names = [child_name for child in children if isinstance(child, dict) if (child_name := _xml_name(child))]
            local_names = _context_names(node.get("local_context"))
            iter_names = _context_names(node.get("iter_local_context"))
            node_id = str(node.get("node_id") or node.get("id") or json_path)
            tree_type = str(node.get("tree_node_type") or node.get("node_type") or node.get("type") or "unknown")
            data_type_value = node.get("data_type") or node.get("data_type_config", {}).get("data_type")
            expression_value = node.get("expression") or node.get("data_expression")
            xml_path = "/".join(current_names)
            parts: list[Any] = [
                name, xml_path, node.get("annotation"), " ".join(semi_text), tree_type,
                data_type_value, *child_names, *local_names, *iter_names, source_summary, ab_bo_name,
            ]
            entry = NodeIndexEntry(
                node_id=node_id,
                json_path=json_path,
                xml_path=xml_path,
                xml_name=name,
                tree_node_type=tree_type,
                annotation=str(node["annotation"]) if node.get("annotation") is not None else None,
                edsl_semistruct_text=" ".join(semi_text),
                data_type=str(data_type_value) if data_type_value is not None else None,
                expression=str(expression_value) if expression_value is not None else None,
                parent_node_id=parent.node_id if parent else None,
                parent_json_path=parent.json_path if parent else None,
                ancestor_xml_names=list(ancestors),
                child_xml_names=child_names,
                local_context_names=local_names,
                iter_local_context_names=iter_names,
                data_source_summary=source_summary,
                ab_bo_name=ab_bo_name,
                search_text=" ".join(str(part) for part in parts if part not in (None, "")),
            )
            result.append(entry)
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    visit(child, f"{json_path}.children[{index}]", entry, current_names)

        visit(root, root_path, None, [])
        return result
