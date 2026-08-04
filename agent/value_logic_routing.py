from dataclasses import dataclass
from typing import Any


AB_CONTAINER_TYPES = frozenset({"ab_pivot_table", "ab_two_level_table", "parent_list"})
KNOWN_TREE_NODE_TYPES = AB_CONTAINER_TYPES | frozenset({"simple_leaf", "parent", "field", "ab_single_mapping_table"})


@dataclass(frozen=True)
class ValueLogicTarget:
    kind: str
    primary_branch: str
    fallback_branch: str | None
    allowed_logic_types: tuple[str, ...]
    priority: tuple[str, ...]
    required_is_list: bool
    is_summary: bool = False


def classify_value_logic_target(node: dict[str, Any]) -> ValueLogicTarget:
    tree_node_type = _tree_node_type(node)
    if tree_node_type not in KNOWN_TREE_NODE_TYPES:
        raise ValueError(f"unknown tree_node_type: {tree_node_type}")

    if tree_node_type == "simple_leaf":
        return ValueLogicTarget(
            "simple_leaf",
            "expression",
            None,
            ("edsl_expression",),
            ("edsl_expression",),
            False,
        )

    if node.get("field_id"):
        if is_summary_field(node):
            return ValueLogicTarget("ab_field", "summary", None, ("summary",), ("summary",), False, True)
        return ValueLogicTarget(
            "ab_field",
            "table_field",
            "expression",
            ("table_field", "edsl_expression"),
            ("table_field", "edsl_expression"),
            False,
        )

    if node.get("node_id") and tree_node_type in AB_CONTAINER_TYPES:
        return ValueLogicTarget(
            "ab_container",
            "sql",
            "expression",
            ("sql", "edsl_expression"),
            ("sql", "edsl_expression"),
            True,
        )

    return ValueLogicTarget(
        "generic",
        "sql",
        "expression",
        ("sql", "edsl_expression"),
        ("sql", "edsl_expression"),
        False,
    )


def _tree_node_type(node: dict[str, Any]) -> str:
    value = node.get("tree_node_type")
    if not isinstance(value, str) or not value:
        raise ValueError("tree_node_type is required")
    return value


def is_summary_field(node: dict[str, Any]) -> bool:
    if _normalize_text(node.get("field_type")) == "summary":
        return True
    if _normalize_summary_type(node.get("summary_type")) is not None:
        return True
    if _normalize_summary_type(node.get("aggregate_type")) is not None:
        return True
    if _normalize_summary_type(node.get("aggregation")) is not None:
        return True

    summary = node.get("summary") or node.get("summary_config")
    if not isinstance(summary, dict):
        return False

    if _normalize_summary_type(summary.get("summary_type")) is not None:
        return True
    if _normalize_summary_type(summary.get("type")) is not None:
        return True
    if _normalize_summary_type(summary.get("aggregation")) is not None:
        return True
    return True


def _normalize_summary_type(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if normalized in {"sum", "count"}:
        return normalized
    return None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()
