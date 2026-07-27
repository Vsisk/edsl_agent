from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    ContextRegistry,
    DataTypeEnum,
    NamingSqlDefTerm,
    ParamTerm,
    PropertyTerm,
    PropertyTypeEnum,
    ReturnType,
)
from agent.spec_orchestration.compiler import ResolutionCompiler
from agent.spec_orchestration.models import (
    GoalRole,
    ResolvedGoal,
    ResourceCandidate,
    ResourceInput,
    SpecOrchestrationResult,
    ValueGoal,
)


def _goal(goal_id, name, type_name="string"):
    return ValueGoal(
        goal_id=goal_id,
        semantic_name=name,
        role=GoalRole.FINAL_OUTPUT,
        expected_type=ReturnType(
            data_type="basic", data_type_name=type_name, is_list=False
        ),
    )


def test_compiler_builds_spec_and_includes_only_committed_context():
    context = ContextRegistry(
        resource_id="ctx.name",
        context_name="$ctx$.customer.name",
        return_type=ReturnType(
            data_type="basic", data_type_name="string", is_list=False
        ),
        property_type=PropertyTypeEnum.system,
        annotation="客户名称",
    )
    goal = _goal("root", "客户名称")
    resolution = ResolvedGoal(
        goal=goal,
        candidate=ResourceCandidate(
            candidate_id=context.resource_id,
            kind="context",
            resource=context,
            return_type=context.return_type,
        ),
    )
    orchestration = SpecOrchestrationResult(
        query="生成客户名称",
        root_goal=goal,
        root_resolution=resolution,
        execution_order=["root"],
    )

    compiled = ResolutionCompiler().compile(orchestration)

    assert compiled.expression_spec.scope_context.inside_parent_list is False
    assert "$ctx$.customer.name" in compiled.expression_spec.nl
    assert compiled.filtered_environment.selected_global_context_ids == ["ctx.name"]
    assert compiled.filtered_environment.selected_bos == []


def test_compiler_builds_compatible_naming_sql_selection_and_trimmed_bo():
    sql = NamingSqlDefTerm(
        naming_sql_id="sql.by_invoice",
        sql_name="QUERY_BY_INVOICE",
        param_list=[ParamTerm(param_name="INVOICE_ID", data_type_name="long")],
    )
    bo = BoRegistry(
        resource_id="bo.bill",
        bo_name="BB_BILL_CUSTGRP",
        bo_desc="账单客户组",
        property_list=[
            PropertyTerm(
                field_name="CUST_GRP_ID",
                data_type=DataTypeEnum.key,
                data_type_name="long",
            ),
            PropertyTerm(
                field_name="UNUSED",
                data_type=DataTypeEnum.basic,
                data_type_name="string",
            ),
        ],
        naming_sql_list=[sql],
    )
    invoice = ContextRegistry(
        resource_id="ctx.invoice",
        context_name="$ctx$.invoice.id",
        return_type=ReturnType(
            data_type="basic", data_type_name="long", is_list=False
        ),
        property_type=PropertyTypeEnum.system,
        annotation="发票ID",
    )
    dependency_goal = _goal("root::INVOICE_ID", "INVOICE_ID", "long")
    dependency = ResolvedGoal(
        goal=dependency_goal,
        candidate=ResourceCandidate(
            candidate_id=invoice.resource_id,
            kind="context",
            resource=invoice,
            return_type=invoice.return_type,
        ),
    )
    root = ValueGoal(
        goal_id="root",
        semantic_name="账单客户组",
        role=GoalRole.INTERMEDIATE_VALUE,
        expected_type=ReturnType(
            data_type="bo", data_type_name=bo.bo_name, is_list=False
        ),
    )
    resolution = ResolvedGoal(
        goal=root,
        candidate=ResourceCandidate(
            candidate_id=f"naming_sql:{bo.bo_name}:{sql.naming_sql_id}",
            kind="naming_sql",
            resource=sql,
            bo_name=bo.bo_name,
            return_type=root.expected_type,
            required_inputs=[
                ResourceInput(name="INVOICE_ID", return_type=invoice.return_type)
            ],
            metadata={"bo": bo},
        ),
        dependencies=[dependency],
        bindings={"INVOICE_ID": dependency_goal.goal_id},
    )
    orchestration = SpecOrchestrationResult(
        query="查询账单客户组",
        root_goal=root,
        root_resolution=resolution,
        execution_order=[dependency_goal.goal_id, root.goal_id],
    )

    compiled = ResolutionCompiler().compile(orchestration)

    selection = compiled.filtered_environment.naming_sql_selection
    assert selection is not None
    assert selection.candidates[0].naming_sql_id == "sql.by_invoice"
    assert compiled.filtered_environment.selected_bos[0].naming_sql_list == [sql]
    assert compiled.filtered_environment.selected_bos[0].property_list == []
    assert "INVOICE_ID" in compiled.expression_spec.nl
    assert "$ctx$.invoice.id" in compiled.expression_spec.nl
