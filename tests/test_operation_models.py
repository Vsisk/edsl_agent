import pytest
from pydantic import ValidationError

from agent.operation_orchestration.models import (
    ExecuteOperationsResponse,
    ExecuteOperationsRequest,
    GenerateOperationsRequest,
    GenerateOperationsResponse,
    LocateOperationRequest,
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


def test_remaining_request_and_response_contracts() -> None:
    operation = make_operation("create")
    target_tree = {"nodes": [{"node_id": "created"}]}

    generate_response = GenerateOperationsResponse(operations=[operation])
    locate_request = LocateOperationRequest(operation=operation, target_tree=target_tree)
    execute_response = ExecuteOperationsResponse(
        success=True,
        target_tree=target_tree,
        operations=[operation],
    )

    assert generate_response.operations == [operation]
    assert locate_request.operation == operation
    assert locate_request.target_tree == target_tree
    assert execute_response.success is True
    assert execute_response.target_tree == target_tree
    assert execute_response.operations == [operation]
    assert execute_response.error_message is None


@pytest.mark.parametrize(
    "intent_type",
    ["create_node", "modify_node", "generate_expression", "delete_node"],
)
def test_operation_accepts_each_intent_type(intent_type: str) -> None:
    operation = Operation(
        op_id="operation",
        query="perform operation",
        intent_type=intent_type,
    )

    assert operation.intent_type == intent_type


def test_operation_rejects_unknown_intent_type() -> None:
    with pytest.raises(ValidationError, match="intent_type"):
        make_operation("invalid", intent_type="move_node")


@pytest.mark.parametrize("status", ["pending", "located", "executed", "failed"])
def test_operation_accepts_each_status(status: str) -> None:
    operation = make_operation("operation", status=status)

    assert operation.status == status


def test_operation_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError, match="status"):
        make_operation("invalid", status="cancelled")


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


def test_validation_does_not_mutate_any_input_operation() -> None:
    operations = [
        make_operation("finish", depends_on=["combine"], status="located"),
        make_operation(
            "combine",
            depends_on=["left", "right"],
            target_from="right",
            target_jsonpath="$.children[0]",
        ),
        make_operation("right", output_node_id="right-node"),
        make_operation("left", target_node_id="left-node"),
    ]
    snapshots = [operation.model_dump(mode="python") for operation in operations]

    validate_and_sort_operations(operations)

    assert [operation.model_dump(mode="python") for operation in operations] == snapshots


def test_empty_operation_list_is_valid() -> None:
    assert validate_and_sort_operations([]) == []
