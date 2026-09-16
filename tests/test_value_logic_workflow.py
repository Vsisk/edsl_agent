from __future__ import annotations

from dataclasses import dataclass

from agent.workflows.value_logic import (
    ValueLogicBranchOutcome,
    ValueLogicExecutionEnvironment,
    ValueLogicWorkflowFactory,
    ValueLogicWorkflowHandler,
)


@dataclass
class Target:
    primary_branch: str


@dataclass
class Request:
    query: str


@dataclass
class GenerationContext:
    marker: str
    filtered_env: object | None = None
    context_pack: dict | None = None


def _handler(**overrides) -> ValueLogicWorkflowHandler:
    defaults = {
        "prepare_context_fn": lambda request: (GenerationContext("ctx"), None),
        "resolve_sql_fn": lambda request, ctx: {"logic_type": "sql"},
        "resolve_bo_field_fn": lambda request, ctx: {"logic_type": "bo"},
        "summary_fn": lambda request, ctx: {"logic_type": "summary"},
        "expression_fn": lambda request, ctx: {"logic_type": "expression"},
    }
    defaults.update(overrides)
    return ValueLogicWorkflowHandler(
        workflow_factory=ValueLogicWorkflowFactory(**defaults)
    )


def _execute(handler: ValueLogicWorkflowHandler):
    request = Request("q")
    environment = ValueLogicExecutionEnvironment(request=request)
    result = handler.execute(request=request, environment=environment)
    return result, handler.last_state, environment.child_run_states


def test_value_logic_workflow_runs_sql_as_child_workflow() -> None:
    handler = _handler(
        prepare_context_fn=lambda request: (GenerationContext("ctx"), Target("sql")),
        resolve_sql_fn=lambda request, ctx: {"logic_type": "sql"},
    )

    result, parent_state, child_states = _execute(handler)

    assert result == {"logic_type": "sql"}
    assert parent_state.workflow_name == "value_logic_generation"
    assert parent_state.artifacts["branch_history"] == ["sql"]
    assert parent_state.artifacts["child_run_id"] == child_states[0].run_id
    assert child_states[0].workflow_name == "sql_value_logic_generation"
    assert child_states[0].parent_run_id == parent_state.run_id


def test_value_logic_workflow_controls_sql_fallback_to_expression() -> None:
    calls = []

    def resolve_sql(request, ctx):
        calls.append("sql")
        ctx.filtered_env = {"selected": ["sql_env"]}
        ctx.context_pack = {"naming_sql_hint": "hint-1"}
        return None

    def run_expression(request, ctx):
        calls.append(("expression", ctx.filtered_env, ctx.context_pack))
        return {"logic_type": "expression"}

    handler = _handler(
        prepare_context_fn=lambda request: (GenerationContext("ctx"), Target("sql")),
        resolve_sql_fn=resolve_sql,
        expression_fn=run_expression,
    )

    result, parent_state, child_states = _execute(handler)

    assert result == {"logic_type": "expression"}
    assert calls == [
        "sql",
        ("expression", {"selected": ["sql_env"]}, {"naming_sql_hint": "hint-1"}),
    ]
    assert parent_state.artifacts["branch_history"] == ["sql", "expression"]
    assert len(child_states) == 2
    assert [state.workflow_name for state in child_states] == [
        "sql_value_logic_generation",
        "expression_generation",
    ]
    assert all(state.parent_run_id == parent_state.run_id for state in child_states)
    sql_outcome = child_states[0].require_artifact("branch_outcome")
    assert isinstance(sql_outcome, ValueLogicBranchOutcome)
    assert sql_outcome.status == "fallback"
    assert sql_outcome.fallback_target == "expression"
    assert sql_outcome.handoff_artifacts["initial_filtered_env"] == {"selected": ["sql_env"]}
    assert sql_outcome.handoff_artifacts["naming_sql_hint"] == "hint-1"


def test_value_logic_workflow_runs_bo_field_as_child_workflow() -> None:
    handler = _handler(
        prepare_context_fn=lambda request: (GenerationContext("ctx"), Target("table_field")),
        resolve_bo_field_fn=lambda request, ctx: {"logic_type": "bo_field_mapping"},
    )

    result, parent_state, child_states = _execute(handler)

    assert result == {"logic_type": "bo_field_mapping"}
    assert parent_state.artifacts["branch_history"] == ["bo_field"]
    assert child_states[0].workflow_name == "bo_field_value_logic_generation"
    assert child_states[0].parent_run_id == parent_state.run_id


def test_value_logic_workflow_controls_bo_field_fallback_to_expression() -> None:
    calls = []
    handler = _handler(
        prepare_context_fn=lambda request: (GenerationContext("ctx"), Target("table_field")),
        resolve_bo_field_fn=lambda request, ctx: calls.append("bo") or None,
        expression_fn=lambda request, ctx: calls.append("expression") or {"logic_type": "expression"},
    )

    result, parent_state, child_states = _execute(handler)

    assert result == {"logic_type": "expression"}
    assert calls == ["bo", "expression"]
    assert parent_state.artifacts["branch_history"] == ["bo_field", "expression"]
    assert [state.workflow_name for state in child_states] == [
        "bo_field_value_logic_generation",
        "expression_generation",
    ]
    assert all(state.parent_run_id == parent_state.run_id for state in child_states)


def test_value_logic_workflow_runs_expression_as_child_workflow() -> None:
    handler = _handler(
        prepare_context_fn=lambda request: (GenerationContext("ctx"), None),
        expression_fn=lambda request, ctx: {"logic_type": "expression"},
    )

    result, parent_state, child_states = _execute(handler)

    assert result == {"logic_type": "expression"}
    assert parent_state.artifacts["branch_history"] == ["expression"]
    assert child_states[0].workflow_name == "expression_generation"
    assert child_states[0].parent_run_id == parent_state.run_id


def test_value_logic_workflow_surfaces_expression_failure() -> None:
    def fail_expression(request, ctx):
        raise RuntimeError("expression failed")

    handler = _handler(
        prepare_context_fn=lambda request: (GenerationContext("ctx"), None),
        expression_fn=fail_expression,
    )

    result, parent_state, child_states = _execute(handler)

    assert result.status == "failed"
    assert result.branch_type == "expression"
    assert parent_state.artifacts["branch_history"] == ["expression"]
    assert child_states[0].parent_run_id == parent_state.run_id


def test_value_logic_workflow_blocks_branch_fallback_loop() -> None:
    handler = _handler(
        prepare_context_fn=lambda request: (GenerationContext("ctx"), Target("sql")),
        resolve_sql_fn=lambda request, ctx: None,
        expression_fn=lambda request, ctx: ValueLogicBranchOutcome(
            status="fallback",
            branch_type="expression",
            fallback_target="sql",
        ),
    )

    result, parent_state, child_states = _execute(handler)

    assert result.status == "failed"
    assert result.branch_type == "value_logic"
    assert parent_state.artifacts["branch_history"] == ["sql", "expression"]
    assert len(child_states) == 2
