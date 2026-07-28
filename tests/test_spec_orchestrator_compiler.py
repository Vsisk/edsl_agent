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
    assert selection[0].namingsql_name == "QUERY_BY_INVOICE"
    assert compiled.filtered_environment.selected_bos[0].naming_sql_list == [sql]
    assert compiled.filtered_environment.selected_bos[0].property_list == []
    assert "INVOICE_ID" in compiled.expression_spec.nl
    assert "$ctx$.invoice.id" in compiled.expression_spec.nl


def test_compiler_projects_bo_select_target_and_condition_fields():
    bo = BoRegistry(
        resource_id="bo.customer",
        bo_name="BO_CUSTOMER",
        bo_desc="客户",
        property_list=[
            PropertyTerm(
                field_name="CUSTOMER_ID",
                data_type=DataTypeEnum.key,
                data_type_name="long",
            ),
            PropertyTerm(
                field_name="NAME",
                data_type=DataTypeEnum.basic,
                data_type_name="string",
            ),
            PropertyTerm(
                field_name="UNUSED",
                data_type=DataTypeEnum.basic,
                data_type_name="string",
            ),
        ],
    )
    key_goal = _goal("root::__bo__:BO_CUSTOMER::CUSTOMER_ID", "CUSTOMER_ID", "long")
    key_resolution = ResolvedGoal(
        goal=key_goal,
        candidate=ResourceCandidate(
            candidate_id="ctx.customer_id",
            kind="context",
            resource=ContextRegistry(
                resource_id="ctx.customer_id",
                context_name="$ctx$.customer.id",
                return_type=ReturnType(
                    data_type="basic", data_type_name="long", is_list=False
                ),
                property_type=PropertyTypeEnum.system,
                annotation="客户ID",
            ),
            return_type=ReturnType(
                data_type="basic", data_type_name="long", is_list=False
            ),
        ),
    )
    bo_goal = ValueGoal(
        goal_id="root::__bo__:BO_CUSTOMER",
        semantic_name="BO_CUSTOMER",
        role=GoalRole.INTERMEDIATE_VALUE,
        expected_type=ReturnType(
            data_type="bo", data_type_name="BO_CUSTOMER", is_list=False
        ),
        target_bo_name="BO_CUSTOMER",
        target_field_name="NAME",
    )
    resolution = ResolvedGoal(
        goal=bo_goal,
        candidate=ResourceCandidate(
            candidate_id="select_one:BO_CUSTOMER:CUSTOMER_ID",
            kind="bo_select",
            resource=bo,
            bo_name="BO_CUSTOMER",
            field_name="NAME",
            return_type=bo_goal.expected_type,
            required_inputs=[
                ResourceInput(
                    name="CUSTOMER_ID",
                    return_type=ReturnType(
                        data_type="key", data_type_name="long", is_list=False
                    ),
                )
            ],
            metadata={
                "bo": bo,
                "operation": "select_one",
                "target_field_name": "NAME",
                "condition_fields": ["CUSTOMER_ID"],
            },
        ),
        dependencies=[key_resolution],
        bindings={"CUSTOMER_ID": key_goal.goal_id},
    )
    orchestration = SpecOrchestrationResult(
        query="获取客户名称",
        root_goal=bo_goal,
        root_resolution=resolution,
        execution_order=[key_goal.goal_id, bo_goal.goal_id],
    )

    compiled = ResolutionCompiler().compile(orchestration)

    assert [
        field.field_name
        for field in compiled.filtered_environment.selected_bos[0].property_list
    ] == ["NAME", "CUSTOMER_ID"]
    assert "select_one" in compiled.expression_spec.nl
    assert "CUSTOMER_ID" in compiled.expression_spec.nl
    assert "$ctx$.customer.id" in compiled.expression_spec.nl
