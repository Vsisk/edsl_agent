from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_directory_exports_core_workflow_types() -> None:
    from agent.workflow.runtime.definition import WorkflowDefinition
    from agent.workflow.runtime.run_state import WorkflowRunState
    from agent.workflow.runtime.runtime import WorkflowRuntime
    from agent.workflow.runtime.stage import Stage
    from agent.workflow.runtime.stage_result import StageResult
    from agent.workflow.runtime.subworkflow import SubWorkflowRequest

    assert WorkflowDefinition.__name__ == "WorkflowDefinition"
    assert WorkflowDefinition.__module__.startswith("agent.workflow.runtime")
    assert WorkflowRunState.__name__ == "WorkflowRunState"
    assert WorkflowRunState.__module__.startswith("agent.workflow.runtime")
    assert WorkflowRuntime.__name__ == "WorkflowRuntime"
    assert WorkflowRuntime.__module__.startswith("agent.workflow.runtime")
    assert Stage.__name__ == "Stage"
    assert Stage.__module__.startswith("agent.workflow.runtime")
    assert StageResult.__name__ == "StageResult"
    assert StageResult.__module__.startswith("agent.workflow.runtime")
    assert SubWorkflowRequest.__name__ == "SubWorkflowRequest"
    assert SubWorkflowRequest.__module__.startswith("agent.workflow.runtime")


def test_concrete_workflows_directory_exports_value_logic_parent_and_children() -> None:
    from agent.workflows.value_logic.definition import ValueLogicWorkflowFactory
    from agent.workflows.value_logic.input import ValueLogicWorkflowInput
    from agent.workflows.value_logic.result import ValueLogicBranchOutcome
    from agent.workflows.value_logic.branches.bo_field.definition import BoFieldWorkflowFactory
    from agent.workflows.value_logic.branches.expression.definition import ExpressionWorkflowFactory
    from agent.workflows.value_logic.branches.sql.definition import SqlValueLogicWorkflowFactory

    assert ValueLogicWorkflowFactory.__name__ == "ValueLogicWorkflowFactory"
    assert ValueLogicWorkflowFactory.__module__.startswith("agent.workflows.value_logic")
    assert ValueLogicWorkflowInput(query="q").query == "q"
    assert ValueLogicBranchOutcome(status="success", branch_type="expression").status == "success"
    assert callable(SqlValueLogicWorkflowFactory)
    assert SqlValueLogicWorkflowFactory.__module__.startswith("agent.workflows.value_logic")
    assert callable(BoFieldWorkflowFactory)
    assert BoFieldWorkflowFactory.__module__.startswith("agent.workflows.value_logic")
    assert ExpressionWorkflowFactory.__name__ == "ExpressionWorkflowFactory"


def test_generic_workflow_layer_contains_no_concrete_workflow_dependencies() -> None:
    generic_workflow_root = PROJECT_ROOT / "agent" / "workflow"

    assert not list((generic_workflow_root / "value_logic").rglob("*.py"))
    for source_path in generic_workflow_root.rglob("*.py"):
        assert "agent.workflows" not in source_path.read_text(encoding="utf-8")
