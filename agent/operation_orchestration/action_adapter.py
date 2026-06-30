from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from agent.generate_node_operation import GenerateNodeOperation, GenerateNodeOperationInput, PathResolver
from agent.models import ValueLogicRequest
from agent.modify_node_operation import ModifyNodeOperation, ModifyNodeOperationInput
from agent.value_logic_generator import ValueLogicGenerator
from models import DataExpressionTerm, DataSourceConfig, TreeNodeTerm


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
        created_id = generated_node.get("node_id") if isinstance(generated_node, dict) else None
        if not _nonblank(created_id) and isinstance(generated_node, dict):
            created_id = generated_node.get("field_id")
        if not _nonblank(created_id):
            raise ValueError("create_node failed: generated node_id or field_id is missing")
        if not isinstance(result.patch, dict):
            raise ValueError("create_node failed: patch is missing")
        updated = _apply_patches(target_tree, [result.patch])
        return {"created_node_id": created_id, "target_tree": updated}

    def modify_node(
        self,
        query: str,
        target_jsonpath: str,
        target_tree: dict[str, Any],
        site_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        result = self.modify_node_operation.execute(
            ModifyNodeOperationInput(
                query=query,
                node_path=target_jsonpath,
                edsl_tree=target_tree,
                site_id=site_id,
                project_id=project_id,
            )
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
        target_type = target.get("tree_node_type")
        ab_parent, ab_parent_tokens = _nearest_ab_parent(ancestors, tokens)
        field_slot = next(
            (
                token
                for token in reversed(tokens)
                if token in {"detail_fields", "group_by_fields", "group_related_fields", "sum_fields", "summary_fields"}
            ),
            None,
        )
        if target_type == "simple_leaf":
            expression_kind = "simple_leaf"
            parent_node = _nearest_node(ancestors)
        elif _nonblank(target.get("field_id")) and ab_parent is not None and field_slot != "summary_fields":
            expression_kind = "ab_common_field"
            parent_node = ab_parent
        else:
            raise ValueError("generate_expression failed: target does not support expression generation")
        result = self.value_logic_generator.generate(
            ValueLogicRequest(
                site_id=site_id or "",
                project_id=project_id or "",
                node_path=target_jsonpath,
                node=target,
                parent_node=parent_node,
                query=query,
                is_ab=expression_kind == "ab_common_field" or _is_ab_node(target) or _is_ab_node(parent_node),
                edsl_tree=target_tree,
            )
        )
        if result.logic_type != "expression":
            raise ValueError("generate_expression failed: result is not expression logic")
        if not _nonblank(result.expression):
            raise ValueError("generate_expression failed: expression is blank")

        updated = deepcopy(target_tree)
        updated_target = _value_at_tokens(updated, tokens)
        expression = DataExpressionTerm(expression=result.expression)
        if expression_kind == "simple_leaf":
            updated_target["data_expression"] = expression.model_dump(mode="json", exclude_none=True)
        else:
            updated_target["data_source"] = DataSourceConfig(
                data_source_type="expression", data_expression=expression
            ).model_dump(mode="json", exclude_none=True)
            TreeNodeTerm.model_validate(_value_at_tokens(updated, ab_parent_tokens))
        return {"target_tree": updated}

    def delete_node(self, target_jsonpath: str, target_tree: dict[str, Any]) -> dict[str, Any]:
        if target_jsonpath.strip() == "$":
            raise ValueError("delete_node failed: root deletion is not allowed")
        target, ancestors, tokens = _resolve_path(target_tree, target_jsonpath)
        if not isinstance(target, dict) or not (
            _nonblank(target.get("node_id")) or _nonblank(target.get("field_id"))
        ):
            raise ValueError("delete_node failed: target node_id or field_id is missing")
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
        updated = _apply_patch(updated, patch)
    return updated


def _apply_patch(document: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    operation = patch.get("op")
    if operation not in {"add", "replace"}:
        raise ValueError(f"patch operation is unsupported: {operation!r}")
    path = patch.get("path")
    if not isinstance(path, str) or (path and not path.startswith("/")) or path == "/":
        raise ValueError("patch path is malformed")
    if "value" not in patch:
        raise ValueError("patch value is missing")
    if path == "":
        if operation != "replace" or not isinstance(patch["value"], dict):
            raise ValueError("patch root only supports replacing the document object")
        return deepcopy(patch["value"])
    segments = [_decode_pointer_segment(part) for part in path[1:].split("/")]

    parent: Any = document
    for segment in segments[:-1]:
        parent = _pointer_child(parent, segment)
    final = segments[-1]
    value = deepcopy(patch["value"])

    if operation == "add":
        if not isinstance(parent, list) or final != "-":
            raise ValueError("patch add only supports appending to a list with '-'")
        parent.append(value)
        return document
    if isinstance(parent, dict):
        if final not in parent:
            raise ValueError("patch replace target does not exist")
        parent[final] = value
        return document
    if isinstance(parent, list):
        parent[_list_index(final, len(parent))] = value
        return document
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
    tokens = list(resolved.tokens)
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


def _nearest_ab_parent(
    ancestors: list[Any], tokens: list[str | int]
) -> tuple[dict[str, Any] | None, list[str | int]]:
    for index in range(len(ancestors) - 1, -1, -1):
        value = ancestors[index]
        if (
            isinstance(value, dict)
            and _nonblank(value.get("node_id"))
            and str(value.get("tree_node_type", "")).startswith("ab_")
        ):
            return value, tokens[:index]
    return None, []


def _is_ab_node(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict):
        return False
    return bool(node.get("is_ab")) or str(node.get("tree_node_type", "")).startswith("ab_")


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
