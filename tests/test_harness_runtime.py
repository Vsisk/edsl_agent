from __future__ import annotations

import pytest

from agent.harness import (
    HarnessContext,
    HarnessRuntime,
    OperationStatus,
    WorkflowMetadata,
    WorkflowRegistry,
    create_default_workflow_registry,
    handle_harness_request,
)
from agent.harness.adapters import LegacyWorkflowAdapter


def test_workflow_registry_registers_metadata_and_rejects_duplicates() -> None:
    registry = WorkflowRegistry()
    metadata = WorkflowMetadata(
        name="expression_generation",
        description="Generate expression",
    )
    registry.register(metadata, LegacyWorkflowAdapter(lambda **_: {"ok": True}))

    assert registry.get("expression_generation").metadata.description == "Generate expression"
    with pytest.raises(ValueError, match="workflow already registered"):
        registry.register(metadata, LegacyWorkflowAdapter(lambda **_: {"ok": True}))


def test_default_registry_exposes_workflow_level_capabilities_only() -> None:
    registry = create_default_workflow_registry(expression_execute=lambda *_: {"expression": "x"})

    names = {metadata.name for metadata in registry.metadata()}

    assert {
        "expression_generation",
        "node_generation",
        "node_modify",
        "ab_data_source_generation",
        "pdf_parse",
        "excel_parse",
    } <= names
    assert "spec_analysis" not in names
    assert "resource_search" not in names
    assert "ast_validation" not in names


def test_single_expression_request_routes_to_expression_workflow() -> None:
    calls = []

    def expression_execute(expression_input, context):
        calls.append((expression_input, context))
        return {"logic_type": "expression", "expression": "customer.name"}

    result = handle_harness_request(
        query="生成客户名称取值逻辑",
        context=HarnessContext(site_id="site1", project_id="project1"),
        expression_execute=expression_execute,
    )

    assert [operation.workflow for operation in result.plan.operations] == ["expression_generation"]
    assert result.results["op_1"].status == OperationStatus.COMPLETED
    assert result.results["op_1"].output["expression"] == "customer.name"
    assert calls[0][0]["query"] == "生成客户名称取值逻辑"
    assert calls[0][1].site_id == "site1"


def test_multi_workflow_request_builds_dependency_plan_and_executes_in_order() -> None:
    execution_order = []

    def node_generation(**kwargs):
        execution_order.append(kwargs["operation"].workflow)
        return {"node_ref": "node-1"}

    def expression_execute(expression_input, context):
        execution_order.append("expression_generation")
        dependency_results = expression_input["dependency_results"]
        assert dependency_results["op_1"].output == {"node_ref": "node-1"}
        return {"expression": "customer.groupName"}

    runtime = HarnessRuntime(
        registry=create_default_workflow_registry(
            expression_execute=expression_execute,
            legacy_adapters={"node_generation": node_generation},
        )
    )

    result = runtime.handle(
        query="新增客户组名称字段，并生成对应的取值逻辑",
        context=HarnessContext(site_id="site1"),
    )

    assert [(operation.op_id, operation.workflow, operation.depends_on) for operation in result.plan.operations] == [
        ("op_1", "node_generation", []),
        ("op_2", "expression_generation", ["op_1"]),
    ]
    assert execution_order == ["node_generation", "expression_generation"]
    assert result.results["op_2"].output == {"expression": "customer.groupName"}


def test_harness_skips_dependent_operations_when_dependency_fails() -> None:
    def failing_node_generation(**_):
        raise RuntimeError("node generation failed")

    result = handle_harness_request(
        query="新增客户组名称字段，并生成对应的取值逻辑",
        expression_execute=lambda *_: {"should_not_run": True},
        legacy_adapters={"node_generation": failing_node_generation},
    )

    assert result.results["op_1"].status == OperationStatus.FAILED
    assert result.results["op_2"].status == OperationStatus.SKIPPED
    assert result.results["op_2"].error == "dependency failed: op_1"


def test_legacy_workflow_without_adapter_reports_unsupported() -> None:
    result = handle_harness_request(query="新增客户组名称字段")

    assert result.plan.operations[0].workflow == "node_generation"
    assert result.results["op_1"].status == OperationStatus.FAILED
    assert "not implemented" in result.results["op_1"].error
