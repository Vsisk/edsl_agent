import pytest

from agent.operation_orchestration.models import (
    ExecuteOperationsRequest,
    GenerateOperationsRequest,
    LocateOperationResponse,
    Operation,
    validate_and_sort_operations,
)


def make_operation(op_id: str, **overrides: object) -> Operation:
    values = {
        "op_id": op_id,
        "query": f"perform {op_id}",
        "intent_type": "create_node",
    }
    values.update(overrides)
    return Operation(**values)


def test_mutable_defaults_are_isolated() -> None:
    first = make_operation("first")
    second = make_operation("second")
    first.depends_on.append("upstream")

    first_response = LocateOperationResponse(success=True, operation=first)
    second_response = LocateOperationResponse(success=True, operation=second)
    first_response.candidates.append({"node_id": "candidate"})

    assert second.depends_on == []
    assert second_response.candidates == []
    assert second.status == "pending"


def test_request_models_accept_tree_payloads() -> None:
    operation = make_operation("create")

    generate = GenerateOperationsRequest(query="create a node", target_tree={"nodes": []})
    execute = ExecuteOperationsRequest(
        operations=[operation],
        target_tree={"nodes": []},
        site_id="site",
        project_id="project",
    )

    assert generate.target_tree == {"nodes": []}
    assert execute.site_id == "site"
    assert execute.project_id == "project"


def test_duplicate_operation_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate op_id"):
        validate_and_sort_operations([make_operation("same"), make_operation("same")])


def test_missing_dependency_is_rejected() -> None:
    operation = make_operation("child", depends_on=["missing"])

    with pytest.raises(ValueError, match="missing dependency"):
        validate_and_sort_operations([operation])


def test_self_dependency_is_rejected() -> None:
    operation = make_operation("loop", depends_on=["loop"])

    with pytest.raises(ValueError, match="self-dependency"):
        validate_and_sort_operations([operation])


def test_target_from_must_be_a_dependency() -> None:
    operations = [
        make_operation("source"),
        make_operation("other"),
        make_operation("child", depends_on=["source"], target_from="other"),
    ]

    with pytest.raises(ValueError, match="target_from.*depends_on"):
        validate_and_sort_operations(operations)


def test_multiple_dependencies_require_target_from() -> None:
    operations = [
        make_operation("left"),
        make_operation("right"),
        make_operation("child", depends_on=["left", "right"]),
    ]

    with pytest.raises(ValueError, match="multiple dependencies.*target_from"):
        validate_and_sort_operations(operations)


def test_cycles_are_rejected() -> None:
    operations = [
        make_operation("first", depends_on=["second"]),
        make_operation("second", depends_on=["first"]),
    ]

    with pytest.raises(ValueError, match="cycle"):
        validate_and_sort_operations(operations)


def test_topological_sort_preserves_input_order_between_ready_siblings() -> None:
    operations = [
        make_operation("third", depends_on=["root"]),
        make_operation("second", depends_on=["root"]),
        make_operation("root"),
        make_operation("independent"),
    ]

    result = validate_and_sort_operations(operations)

    assert [operation.op_id for operation in result] == [
        "root",
        "third",
        "second",
        "independent",
    ]
    assert operations[0].op_id == "third"


def test_valid_multi_dependency_graph_is_sorted() -> None:
    operations = [
        make_operation("publish", depends_on=["combine"]),
        make_operation(
            "combine",
            depends_on=["left", "right"],
            target_from="left",
        ),
        make_operation("right"),
        make_operation("left"),
    ]

    result = validate_and_sort_operations(operations)

    assert [operation.op_id for operation in result] == [
        "right",
        "left",
        "combine",
        "publish",
    ]


def test_empty_operation_list_is_valid() -> None:
    assert validate_and_sort_operations([]) == []
