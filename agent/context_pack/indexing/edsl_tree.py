from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


def _xml_name(node: dict[str, Any]) -> str | None:
    value = node.get("xml_name_property")
    if isinstance(value, dict) and value.get("xml_name"):
        return str(value["xml_name"])
    return None


@dataclass(frozen=True, slots=True)
class EdslIndexEntry:
    item_id: str
    source_id: str
    item_type: str
    node_id: str
    json_path: str
    xml_path: str
    parent_node_id: str | None
    ancestor_node_ids: tuple[str, ...]
    tree_node_type: str
    name: str | None
    annotation: str | None
    data_type: str | None
    field_role: str | None
    search_text: str
    content: dict[str, Any] = field(default_factory=dict)


class EdslIndexBuilder:
    def __init__(self, max_content_chars: int = 2000) -> None:
        self.max_content_chars = max_content_chars

    def build(self, tree: dict[str, Any], source_id: str) -> list[EdslIndexEntry]:
        if not isinstance(tree, dict) or not tree:
            raise ValueError("EDSL tree must be a non-empty object")
        has_mapping = isinstance(tree.get("mapping_content"), dict)
        root = tree["mapping_content"] if has_mapping else tree
        root_path = "$.mapping_content" if has_mapping else "$"
        result: list[EdslIndexEntry] = []

        def visit(node, json_path, parent_id, ancestors, xml_ancestors):
            node_id = str(node.get("node_id") or node.get("id") or json_path)
            node_type = str(node.get("tree_node_type") or node.get("node_type") or "unknown")
            name = _xml_name(node)
            xml_names = (*xml_ancestors, name) if name else xml_ancestors
            xml_path = "/".join(xml_names)
            data_type = node.get("data_type")
            if data_type is None and isinstance(node.get("data_type_config"), dict):
                data_type = node["data_type_config"].get("data_type") or node["data_type_config"].get("data_type_name")
            item_type = "field" if node_type == "simple_leaf" else "node"
            result.append(self._entry(
                source_id, item_type, node_id, json_path, xml_path, parent_id, ancestors,
                node_type, name, node.get("annotation"), data_type, None, self._node_content(node),
            ))
            self._append_variables(result, source_id, node, node_id, json_path, xml_path, ancestors, node_type)
            self._append_table_fields(result, source_id, node, node_id, json_path, xml_path, ancestors, node_type)
            children = node.get("children") if isinstance(node.get("children"), list) else []
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    visit(child, f"{json_path}.children[{index}]", node_id, (*ancestors, node_id), xml_names)

        visit(root, root_path, None, (), ())
        return result

    def _entry(self, source_id, item_type, node_id, json_path, xml_path, parent_id,
               ancestors, node_type, name, annotation, data_type, role, content):
        raw_id = f"{source_id}|{item_type}|{json_path}"
        item_id = f"edsl:{hashlib.sha256(raw_id.encode()).hexdigest()[:20]}"
        search_text = " ".join(str(value) for value in (
            name, annotation, node_type, data_type, role, xml_path, *content.values()
        ) if value not in (None, ""))
        return EdslIndexEntry(
            item_id=item_id, source_id=source_id, item_type=item_type, node_id=node_id,
            json_path=json_path, xml_path=xml_path, parent_node_id=parent_id,
            ancestor_node_ids=tuple(ancestors), tree_node_type=node_type,
            name=str(name) if name is not None else None,
            annotation=str(annotation) if annotation is not None else None,
            data_type=str(data_type) if data_type is not None else None,
            field_role=role, search_text=search_text, content=content,
        )

    def _node_content(self, node):
        keys = ("node_id", "tree_node_type", "annotation", "xml_name_property", "data_type_config", "edsl_semi_struct")
        content = {key: node[key] for key in keys if key in node}
        while len(str(content)) > self.max_content_chars and content:
            content.pop(next(reversed(content)))
        return content

    def _append_variables(self, result, source_id, node, node_id, path, xml_path, ancestors, node_type):
        for field_name, item_type in (("local_context", "local"), ("lobal_context", "local"), ("iter_local_context", "iter")):
            values = node.get(field_name) if isinstance(node.get(field_name), list) else []
            for index, value in enumerate(values):
                if not isinstance(value, dict):
                    continue
                name = value.get("property_name") or value.get("name")
                if not name:
                    continue
                data_type = value.get("return_type", {}).get("data_type_name") if isinstance(value.get("return_type"), dict) else None
                result.append(self._entry(
                    source_id, item_type, node_id, f"{path}.{field_name}[{index}]", xml_path,
                    node_id, (*ancestors, node_id), node_type, name, value.get("annotation"),
                    data_type, item_type, dict(value),
                ))

    def _append_table_fields(self, result, source_id, node, node_id, path, xml_path, ancestors, node_type):
        content = node.get("ab_content") if isinstance(node.get("ab_content"), dict) else {}
        groups = (("detail_fields", "detail"), ("group_by_fields", "group"), ("summary_fields", "summary"))
        for field_name, role in groups:
            values = content.get(field_name) if isinstance(content.get(field_name), list) else []
            for index, value in enumerate(values):
                if not isinstance(value, dict):
                    continue
                name = value.get("field_name") or value.get("name")
                if not name:
                    continue
                result.append(self._entry(
                    source_id, "field", node_id, f"{path}.ab_content.{field_name}[{index}]",
                    xml_path, node_id, (*ancestors, node_id), node_type, name,
                    value.get("annotation") or value.get("description"), value.get("data_type_name"),
                    role, dict(value),
                ))
