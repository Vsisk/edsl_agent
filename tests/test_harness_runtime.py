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
from agent.harness.adapters import LegacyCallableWorkflowAdapter, LegacyWorkflowAdapter
from agent.harness.adapters import WorkflowRuntimeAdapter
from agent.workflow.value_logic import ValueLogicExecutionEnvironment, ValueLogicWorkflowFactory


class _Target:
    primary_branch = "expression"


class _GenerationContext:
    marker = "ctx"


def _fake_value_logic_factory(result: dict | None = None) -> ValueLogicWorkflowFactory:
    return ValueLogicWorkflowFactory(
        prepare_context_fn=lambda request: (_GenerationContext(), _Target()),
        resolve_sql_fn=lambda request, ctx: {"logic_type": "sql"},
        resolve_bo_field_fn=lambda request, ctx: {"logic_type": "bo"},
        summary_fn=lambda request, ctx: {"logic_type": "summary"},
        expression_fn=lambda request, ctx: result or {"logic_type": "expression", "expression": "customer.name"},
    )


def _value_logic_environment_builder(*, workflow_input, context, operation, dependency_results):
    assert workflow_input["query"] == operation.query
    return ValueLogicExecutionEnvironment(request=workflow_input)


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


def test_legacy_callable_workflow_adapter_is_the_callback_adapter_name() -> None:
    adapter = LegacyCallableWorkflowAdapter(lambda workflow_input, context: workflow_input)

    assert adapter is not None


def test_default_registry_exposes_workflow_level_capabilities_only() -> None:
    registry = create_default_workflow_registry(
        value_logic_workflow_factory=_fake_value_logic_factory({"expression": "x"}),
        value_logic_environment_builder=_value_logic_environment_builder,
    )

    metadata_by_name = {metadata.name: metadata for metadata in registry.metadata()}
    names = set(metadata_by_name)

    assert {
        "value_logic_generation",
        "expression_generation",
        "sql_value_logic_generation",
        "bo_field_value_logic_generation",
        "node_generation",
        "node_modify",
        "ab_data_source_generation",
        "pdf_parse",
        "excel_parse",
    } <= names
    assert "spec_analysis" not in names
    assert "resource_search" not in names
    assert "ast_validation" not in names
    assert metadata_by_name["value_logic_generation"].visibility == "public"
    assert metadata_by_name["expression_generation"].visibility == "internal"
    assert metadata_by_name["sql_value_logic_generation"].visibility == "internal"
    assert metadata_by_name["bo_field_value_logic_generation"].visibility == "internal"
    assert isinstance(registry.get("value_logic_generation").adapter, WorkflowRuntimeAdapter)


def test_single_expression_request_routes_to_value_logic_workflow_runtime() -> None:
    result = handle_harness_request(
        query="生成客户名称取值逻辑",
        context=HarnessContext(site_id="site1", project_id="project1"),
        value_logic_workflow_factory=_fake_value_logic_factory(),
        value_logic_environment_builder=_value_logic_environment_builder,
    )

    assert [operation.workflow for operation in result.plan.operations] == ["value_logic_generation"]
    assert result.results["op_1"].status == OperationStatus.COMPLETED
    assert result.results["op_1"].output["expression"] == "customer.name"


def test_multi_workflow_request_builds_dependency_plan_and_executes_in_order() -> None:
    execution_order = []

    def node_generation(**kwargs):
        execution_order.append(kwargs["operation"].workflow)
        return {"node_ref": "node-1"}

    def value_logic_environment_builder(*, workflow_input, context, operation, dependency_results):
        execution_order.append("value_logic_generation")
        assert dependency_results["op_1"].output == {"node_ref": "node-1"}
        return ValueLogicExecutionEnvironment(request=workflow_input)

    runtime = HarnessRuntime(
        registry=create_default_workflow_registry(
            value_logic_workflow_factory=_fake_value_logic_factory({"expression": "customer.groupName"}),
            value_logic_environment_builder=value_logic_environment_builder,
            legacy_adapters={"node_generation": node_generation},
        )
    )

    result = runtime.handle(
        query="新增客户组名称字段，并生成对应的取值逻辑",
        context=HarnessContext(site_id="site1"),
    )

    assert [(operation.op_id, operation.workflow, operation.depends_on) for operation in result.plan.operations] == [
        ("op_1", "node_generation", []),
        ("op_2", "value_logic_generation", ["op_1"]),
    ]
    assert execution_order == ["node_generation", "value_logic_generation"]
    assert result.results["op_2"].output == {"expression": "customer.groupName"}


def test_harness_skips_dependent_operations_when_dependency_fails() -> None:
    def failing_node_generation(**_):
        raise RuntimeError("node generation failed")

    result = handle_harness_request(
        query="新增客户组名称字段，并生成对应的取值逻辑",
        value_logic_workflow_factory=_fake_value_logic_factory({"should_not_run": True}),
        value_logic_environment_builder=_value_logic_environment_builder,
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
