from __future__ import annotations

import re
import json
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.llm.generate_by_llm import generate_by_llm


BusinessLevel = Literal["bill", "acct", "sub"]


class BusinessPathContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_path: str = ""
    business_path: list[str] = Field(default_factory=list)
    business_path_text: str = ""
    business_level: BusinessLevel = "sub"
    business_scope: BusinessLevel = "sub"
    business_level_label: str = "用户级"


class BusinessScopeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scope: BusinessLevel = "sub"


class LLMBusinessScopeClassifier:
    def __init__(self, decision_fn: Callable[..., Any] = generate_by_llm) -> None:
        self.decision_fn = decision_fn

    def classify(
        self,
        *,
        node_path: str,
        business_path: list[str],
        current_node: dict[str, Any],
    ) -> BusinessLevel:
        try:
            raw = self.decision_fn(
                prompt_template="business_scope_classifier",
                llm_name="base",
                lang="zh",
                node_path=str(node_path or "")[:4000],
                business_path_json=_dump(business_path),
                business_path_text="/".join(business_path),
                current_node_json=_dump(current_node),
            )
            return BusinessScopeResponse.model_validate(raw).scope
        except Exception:
            return "sub"


def build_business_path_context(
    *,
    edsl_tree: dict[str, Any] | None,
    node_path: str,
    current_node: dict[str, Any],
    scope_classifier: Any | None = None,
) -> BusinessPathContext:
    normalized_path = _normalize_node_path(node_path)
    path_nodes = _resolve_path_nodes(edsl_tree or {}, normalized_path)
    if not path_nodes:
        path_nodes = [current_node]
    elif _xml_name(path_nodes[-1]) != _xml_name(current_node):
        path_nodes.append(current_node)

    business_path = _compact_names(_xml_name(node) for node in path_nodes)
    classifier = scope_classifier or LLMBusinessScopeClassifier()
    business_level = classifier.classify(
        node_path=normalized_path,
        business_path=business_path,
        current_node=current_node,
    )
    return BusinessPathContext(
        node_path=normalized_path,
        business_path=business_path,
        business_path_text="/".join(business_path),
        business_level=business_level,
        business_scope=business_level,
        business_level_label=_BUSINESS_LEVEL_LABELS[business_level],
    )


def _normalize_node_path(node_path: str) -> str:
    path = (node_path or "").strip()
    if path and not path.startswith("$"):
        path = f"$.{path.lstrip('.')}"
    return path


def _resolve_path_nodes(edsl_tree: dict[str, Any], node_path: str) -> list[dict[str, Any]]:
    if not node_path.startswith("$"):
        return []
    tokens = _parse_node_path_tokens(node_path)
    if tokens is None:
        return []

    value: Any = edsl_tree
    nodes: list[dict[str, Any]] = []
    if isinstance(value, dict):
        nodes.append(value)
    for token in tokens:
        try:
            if isinstance(token, int):
                if not isinstance(value, list):
                    return []
                value = value[token]
            else:
                if not isinstance(value, dict):
                    return []
                value = value[token]
        except (KeyError, IndexError):
            return []
        if isinstance(value, dict):
            nodes.append(value)
    return nodes


def _parse_node_path_tokens(node_path: str) -> list[str | int] | None:
    tokens: list[str | int] = []
    position = 1
    while position < len(node_path):
        if node_path[position] == ".":
            match = _IDENTIFIER.match(node_path, position + 1)
            if match is None:
                return None
            tokens.append(match.group(0))
            position = match.end()
            continue
        if node_path[position] != "[":
            return None
        position += 1
        if position < len(node_path) and node_path[position] == "'":
            position += 1
            chars: list[str] = []
            while position < len(node_path) and node_path[position] != "'":
                if node_path[position] == "\\":
                    position += 1
                    if position >= len(node_path) or node_path[position] not in {"\\", "'"}:
                        return None
                chars.append(node_path[position])
                position += 1
            if position >= len(node_path) or node_path[position] != "'":
                return None
            position += 1
            if position >= len(node_path) or node_path[position] != "]":
                return None
            position += 1
            tokens.append("".join(chars))
            continue
        end = node_path.find("]", position)
        if end < 0:
            return None
        index_text = node_path[position:end]
        if not re.fullmatch(r"0|[1-9][0-9]*", index_text):
            return None
        tokens.append(int(index_text))
        position = end + 1
    return tokens


def _xml_name(node: dict[str, Any]) -> str:
    xml_name_property = node.get("xml_name_property")
    if not isinstance(xml_name_property, dict):
        return ""
    return str(xml_name_property.get("xml_name") or "").strip()


def _compact_names(names: Any) -> list[str]:
    result: list[str] = []
    for name in names:
        if not name:
            continue
        if result and result[-1] == name:
            continue
        result.append(name)
    return result


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))[:12000]


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BUSINESS_LEVEL_LABELS: dict[BusinessLevel, str] = {
    "bill": "账单级",
    "acct": "账户级",
    "sub": "用户级",
}
