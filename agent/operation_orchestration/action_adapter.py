from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from agent.generate_node_operation import GenerateNodeOperation, GenerateNodeOperationInput, PathResolver
from agent.models import ValueLogicRequest
from agent.modify_node_operation import ModifyNodeOperation, ModifyNodeOperationInput
from agent.value_logic_generator import ValueLogicGenerator
from models import DataExpressionTerm


class OperationActionAdapter:
    """Adapt existing node operations to deterministic tree transformations."""

    def __init__(
        self,
        *,
        generate_node_operation: GenerateNodeOperation | None = None,
        modify_node_operation: ModifyNodeOperation | None = None,
        value_logic_generator: ValueLogicGenerator | None = None,
    ) -> None:
        self.generate_node_operation = generate_node_operation or GenerateNodeOperation()
        self.modify_node_operation = modify_node_operation or ModifyNodeOperation()
        self.value_logic_generator = value_logic_generator or ValueLogicGenerator()

    def create_node(self, query: str, target_jsonpath: str, target_tree: dict[str, Any]) -> dict[str, Any]:
        result = self.generate_node_operation.execute(
            GenerateNodeOperationInput(query=query, node_path=target_jsonpath, edsl_tree=target_tree)
        )
        if not result.success:
            raise ValueError(f"create_node failed: {result.failure_reason or 'unknown failure'}")
        generated_node = result.generated_node
        if not isinstance(generated_node, dict) or not _nonblank(generated_node.get("node_id")):
            raise ValueError("create_node failed: generated node_id is missing")
        if not isinstance(result.patch, dict):
            raise ValueError("create_node failed: patch is missing")
        updated = _apply_patches(target_tree, [result.patch])
        return {"created_node_id": generated_node["node_id"], "target_tree": updated}

    def modify_node(self, query: str, target_jsonpath: str, target_tree: dict[str, Any]) -> dict[str, Any]:
        result = self.modify_node_operation.execute(
            ModifyNodeOperationInput(query=query, node_path=target_jsonpath, edsl_tree=target_tree)
        )
        if not result.success:
            raise ValueError(f"modify_node failed: {result.failure_reason or 'unknown failure'}")
        if not isinstance(result.patch_list, list) or not result.patch_list:
            raise ValueError("modify_node failed: patch_list is empty")
        return {"target_tree": _apply_patches(target_tree, result.patch_list)}

    def generate_expression(
        self,
        query: str,
        target_jsonpath: str,
        target_tree: dict[str, Any],
        site_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        target, ancestors, tokens = _resolve_path(target_tree, target_jsonpath)
        if not isinstance(target, dict):
            raise ValueError("generate_expression failed: target must be a node object")
        parent_node = _nearest_node(ancestors)
        result = self.value_logic_generator.generate(
            ValueLogicRequest(
                site_id=site_id or "",
                project_id=project_id or "",
                node_path=target_jsonpath,
                node=target,
                parent_node=parent_node,
                query=query,
                is_ab=_is_ab_node(target) or _is_ab_node(parent_node),
                edsl_tree=target_tree,
            )
        )
        if result.logic_type != "expression":
            raise ValueError("generate_expression failed: result is not expression logic")
        if not _nonblank(result.expression):
            raise ValueError("generate_expression failed: expression is blank")

        updated = deepcopy(target_tree)
        updated_target = _value_at_tokens(updated, tokens)
        updated_target["data_expression"] = DataExpressionTerm(expression=result.expression).model_dump(
            mode="json", exclude_none=True
        )
        return {"target_tree": updated}

    def delete_node(self, target_jsonpath: str, target_tree: dict[str, Any]) -> dict[str, Any]:
        if target_jsonpath.strip() == "$":
            raise ValueError("delete_node failed: root deletion is not allowed")
        target, ancestors, tokens = _resolve_path(target_tree, target_jsonpath)
        if not isinstance(target, dict) or not _nonblank(target.get("node_id")):
            raise ValueError("delete_node failed: target node_id is missing")
        if not tokens or not isinstance(tokens[-1], int):
            raise ValueError("delete_node failed: target is not an element of a list")
        parent_node = _nearest_node(ancestors)
        if parent_node is None:
            raise ValueError("delete_node failed: parent node_id is missing")

        updated = deepcopy(target_tree)
        container = _value_at_tokens(updated, tokens[:-1])
        if not isinstance(container, list):
            raise ValueError("delete_node failed: target is not an element of a list")
        del container[tokens[-1]]
        return {"parent_node_id": parent_node["node_id"], "target_tree": updated}


def _apply_patches(tree: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    updated = deepcopy(tree)
    for patch in patches:
        _apply_patch(updated, patch)
    return updated


def _apply_patch(document: dict[str, Any], patch: dict[str, Any]) -> None:
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    operation = patch.get("op")
    if operation not in {"add", "replace"}:
        raise ValueError(f"patch operation is unsupported: {operation!r}")
    path = patch.get("path")
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        raise ValueError("patch path is malformed")
    if "value" not in patch:
        raise ValueError("patch value is missing")
    segments = [_decode_pointer_segment(part) for part in path[1:].split("/")]
    if any(part in {".", ".."} for part in segments):
        raise ValueError("patch path attempts to escape the document")

    parent: Any = document
    for segment in segments[:-1]:
        parent = _pointer_child(parent, segment)
    final = segments[-1]
    value = deepcopy(patch["value"])

    if operation == "add":
        if not isinstance(parent, list) or final != "-":
            raise ValueError("patch add only supports appending to a list with '-'")
        parent.append(value)
        return
    if isinstance(parent, dict):
        if final not in parent:
            raise ValueError("patch replace target does not exist")
        parent[final] = value
        return
    if isinstance(parent, list):
        parent[_list_index(final, len(parent))] = value
        return
    raise ValueError("patch replace parent is not a container")


def _decode_pointer_segment(segment: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(segment):
        if segment[index] != "~":
            output.append(segment[index])
            index += 1
            continue
        if index + 1 >= len(segment) or segment[index + 1] not in {"0", "1"}:
            raise ValueError("patch path contains malformed JSON Pointer escaping")
        output.append("~" if segment[index + 1] == "0" else "/")
        index += 2
    return "".join(output)


def _pointer_child(parent: Any, segment: str) -> Any:
    if isinstance(parent, dict):
        if segment not in parent:
            raise ValueError("patch path does not exist")
        return parent[segment]
    if isinstance(parent, list):
        return parent[_list_index(segment, len(parent))]
    raise ValueError("patch path traverses a non-container")


def _list_index(segment: str, length: int) -> int:
    if not re.fullmatch(r"0|[1-9][0-9]*", segment):
        raise ValueError("patch list index is malformed")
    index = int(segment)
    if index >= length:
        raise ValueError("patch list index is out of range")
    return index


def _resolve_path(tree: dict[str, Any], path: str) -> tuple[Any, list[Any], list[str | int]]:
    resolved = PathResolver().resolve_value(tree, path)
    tokens: list[str | int] = []
    for match in PathResolver._SEGMENT.finditer(resolved.normalized_path):
        tokens.append(match.group(1) if match.group(1) is not None else int(match.group(2)))
    current: Any = tree
    ancestors: list[Any] = []
    for token in tokens:
        ancestors.append(current)
        current = current[token]
    return current, ancestors, tokens


def _value_at_tokens(tree: Any, tokens: list[str | int]) -> Any:
    current = tree
    for token in tokens:
        current = current[token]
    return current


def _nearest_node(values: list[Any]) -> dict[str, Any] | None:
    for value in reversed(values):
        if isinstance(value, dict) and _nonblank(value.get("node_id")):
            return value
    return None


def _is_ab_node(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict):
        return False
    return bool(node.get("is_ab")) or str(node.get("tree_node_type", "")).startswith("ab_")


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
