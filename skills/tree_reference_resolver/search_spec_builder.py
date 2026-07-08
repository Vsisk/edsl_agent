from __future__ import annotations

import re

from .models import NodeIndexEntry, ReferenceSearchSpec, TreeReferenceResolveInput


_TOKEN_RE = re.compile(r"[A-Za-z]+(?:[A-Z][a-z]*)*|[\u4e00-\u9fff]+|\d+")


def tokenize(text: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text.replace("_", " ").replace("/", " "))
    tokens = [match.group(0).lower() for match in _TOKEN_RE.finditer(expanded)]
    return list(dict.fromkeys(token for token in tokens if token))


class SearchSpecBuilder:
    def build(self, request: TreeReferenceResolveInput, node_index: list[NodeIndexEntry]) -> ReferenceSearchSpec:
        del node_index  # Reserved for future corpus-aware keyword expansion.
        target_name = request.target_node.get("xml_name_property", {}).get("xml_name", "")
        target_annotation = request.target_node.get("annotation", "")
        source_text = " ".join(str(value) for value in (target_name, target_annotation, request.query, request.annotation) if value)
        keywords = tokenize(source_text)
        expected_types = list(request.expected_node_types)
        lowered = source_text.lower()
        constraints: list[str] = []
        if not expected_types:
            if any(term in lowered for term in ("列表", "明细", "迭代", "循环", "table reference", "reference list", "parent_list")):
                expected_types = ["parent_list"]
                constraints.append("must have list-like structural evidence")
            elif any(term in lowered for term in ("费用表", "pivot", "two level", "ab", "分组汇总")):
                expected_types = ["ab"]
                constraints.append("must contain ab_content")
            elif any(term in lowered for term in ("字段", "取值", "叶子节点", "leaf")):
                expected_types = ["simple_leaf"]
                constraints.append("must have leaf value configuration")
        return ReferenceSearchSpec(
            target_summary=source_text,
            target_keywords=keywords,
            expected_node_types=expected_types,
            structural_constraints=constraints,
            negative_constraints=["exclude target node", "exclude descendants of target node"],
        )
