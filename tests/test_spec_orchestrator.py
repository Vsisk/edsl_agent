import threading

from agent.resource_manager.loader.registry_models import ReturnType
from agent.spec_orchestration.models import (
    CoverageDecision,
    CoverageKind,
    GoalRole,
    ResourceCandidate,
    ResourceInput,
    ResourceTier,
    QueryClassification,
    QueryClassificationKind,
    QueryDecomposition,
    QueryPlanKind,
    ValueGoal,
)
from agent.spec_orchestration.orchestrator import SpecOrchestrator
from agent.spec_orchestration.semantic import KeywordDecision


class FakeSemantic:
    def __init__(self, root_goal, decisions):
        self.root_goal = root_goal
        self.decisions = decisions
        self.coverage_calls = []
        self.keyword_calls = []
        self.generated_goal_ids = []

    def classify_query(self, **_):
        return QueryClassification(kind=QueryClassificationKind.SINGLE_GOAL)

    def generate_goal(self, *, goal_id, query, expected_type, role, **_):
        self.generated_goal_ids.append(goal_id)
        if goal_id == "root":
            return self.root_goal.model_copy(deep=True)
        return ValueGoal(
            goal_id=goal_id,
            semantic_name=query,
            role=role,
            expected_type=expected_type.model_copy(deep=True),
        )

    def generate_keywords(self, *, goal, query):
        del query
        self.keyword_calls.append(goal.goal_id)
        return KeywordDecision(keywords=[goal.semantic_name])

    def decide_coverage(self, *, goal, tier, candidates, query):
        del query
        self.coverage_calls.append((goal.goal_id, tier, [c.candidate_id for c in candidates]))
        decision = self.decisions[(goal.semantic_name, tier)]
        if isinstance(decision, list):
            return decision.pop(0)
        return decision


class FakeSearch:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []
        self.requests = []

    def search(self, request):
        self.requests.append(request.model_copy(deep=True))
        self.calls.append((request.goal.semantic_name, request.tier))
        return list(self.candidates.get((request.goal.semantic_name, request.tier), []))


def _goal(name, type_name="string", role=GoalRole.FINAL_OUTPUT, goal_id="root"):
    return ValueGoal(
        goal_id=goal_id,
        semantic_name=name,
        role=role,
        expected_type=ReturnType(
            data_type="basic", data_type_name=type_name, is_list=False
        ),
    )


def _candidate(candidate_id, *, kind="context", type_name="string", inputs=None):
    return ResourceCandidate(
        candidate_id=candidate_id,
        kind=kind,
        resource={"id": candidate_id},
        return_type=ReturnType(
            data_type="basic", data_type_name=type_name, is_list=False
        ),
        required_inputs=inputs or [],
    )


def test_context_cover_stops_lower_priority_search():
    context = _candidate("ctx.name")
    semantic = FakeSemantic(
        _goal("客户名称"),
        {
            ("客户名称", ResourceTier.VISIBLE_VALUE): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id="ctx.name",
                reason="direct context",
            )
        },
    )
    search = FakeSearch({("客户名称", ResourceTier.VISIBLE_VALUE): [context]})

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "客户名称"},
        query="生成客户名称",
        expected_type=_goal("x").expected_type,
    )

    assert result.root_resolution.candidate.candidate_id == "ctx.name"
    assert search.calls == [("客户名称", ResourceTier.VISIBLE_VALUE)]


def test_fixed_string_classification_bypasses_decomposition_goal_and_search():
    class LiteralSemantic:
        def configure_background(self, **_):
            pass

        def classify_query(self, **_):
            return QueryClassification(
                kind=QueryClassificationKind.FIXED_STRING,
                fixed_value="固定值",
            )

        def decompose_multi_goal(self, **_):
            raise AssertionError("fixed string must not be decomposed")

        def generate_goal(self, **_):
            raise AssertionError("literal must not create a searched goal")

        def generate_keywords(self, **_):
            raise AssertionError("literal must not generate keywords")

    class NoSearch:
        def search(self, _):
            raise AssertionError("literal must not search resources")

    result = SpecOrchestrator(
        semantic=LiteralSemantic(),
        search=NoSearch(),
    ).resolve(
        node_info={"node_name": "状态"},
        query='固定填写"固定值"',
        expected_type=_goal("x").expected_type,
    )

    assert result.root_resolution.candidate.kind == "literal"
    assert result.root_resolution.candidate.metadata["value"] == "固定值"
    assert result.execution_order == ["root"]


def test_multi_goal_decomposition_resolves_targets_in_parallel_and_keeps_order():
    barrier = threading.Barrier(2)
    first = _candidate("ctx.first_name")
    last = _candidate("ctx.last_name")

    class ComposeSemantic(FakeSemantic):
        def classify_query(self, **_):
            return QueryClassification(kind=QueryClassificationKind.MULTI_GOAL)

        def decompose_multi_goal(self, **_):
            return QueryDecomposition(
                kind=QueryPlanKind.MULTI_TARGET,
                target_semantic_names=["first name", "last name"],
            )

    class ParallelSearch(FakeSearch):
        def search(self, request):
            if request.tier == ResourceTier.VISIBLE_VALUE:
                barrier.wait(timeout=2)
            return super().search(request)

    semantic = ComposeSemantic(
        _goal("unused"),
        {
            ("first name", ResourceTier.VISIBLE_VALUE): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=first.candidate_id,
                reason="first name context",
            ),
            ("last name", ResourceTier.VISIBLE_VALUE): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=last.candidate_id,
                reason="last name context",
            ),
        },
    )
    search = ParallelSearch(
        {
            ("first name", ResourceTier.VISIBLE_VALUE): [first],
            ("last name", ResourceTier.VISIBLE_VALUE): [last],
        }
    )

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "full_name"},
        query='用"_"拼接 first name 和 last name',
        expected_type=_goal("x").expected_type,
    )

    assert result.root_resolution.candidate.kind == "goal_set"
    assert [
        dependency.candidate.kind
        for dependency in result.root_resolution.dependencies
    ] == ["context", "context"]
    assert [
        dependency.goal.semantic_name
        for dependency in result.root_resolution.dependencies
    ] == ["first name", "last name"]
    assert sorted(semantic.generated_goal_ids) == [
        "root::target:0",
        "root::target:1",
    ]


def test_multi_goal_decomposition_does_not_model_if_expression_parts():
    condition = _candidate("ctx.customer_is_active")
    value = _candidate("ctx.customer_name")

    class IfSemantic(FakeSemantic):
        def classify_query(self, **_):
            return QueryClassification(kind=QueryClassificationKind.MULTI_GOAL)

        def decompose_multi_goal(self, **_):
            return QueryDecomposition(
                kind=QueryPlanKind.MULTI_TARGET,
                target_semantic_names=["customer is active", "customer name"],
            )

    semantic = IfSemantic(
        _goal("unused"),
        {
            ("customer is active", ResourceTier.VISIBLE_VALUE): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=condition.candidate_id,
                reason="condition context",
            ),
            ("customer name", ResourceTier.VISIBLE_VALUE): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=value.candidate_id,
                reason="value context",
            ),
        },
    )
    search = FakeSearch(
        {
            ("customer is active", ResourceTier.VISIBLE_VALUE): [condition],
            ("customer name", ResourceTier.VISIBLE_VALUE): [value],
        }
    )

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "display_name"},
        query="如果客户有效则使用客户名称，否则填写 inactive",
        expected_type=_goal("x").expected_type,
    )

    assert result.root_resolution.candidate.kind == "goal_set"
    assert "operator" not in result.root_resolution.candidate.metadata
    assert [
        dependency.goal.semantic_name
        for dependency in result.root_resolution.dependencies
    ] == ["customer is active", "customer name"]
    assert sorted(semantic.generated_goal_ids) == [
        "root::target:0",
        "root::target:1",
    ]


def test_naming_sql_is_committed_only_after_parameter_goal_resolves():
    field = ResourceCandidate(
        candidate_id="bo.bill_custgrp:field:CUST_GRP_NAME",
        kind="bo_field",
        resource={"bo": "BB_BILL_CUSTGRP"},
        bo_name="BB_BILL_CUSTGRP",
        field_name="CUST_GRP_NAME",
        return_type=ReturnType(
            data_type="basic", data_type_name="string", is_list=False
        ),
    )
    invoice_input = ResourceInput(
        name="INVOICE_ID",
        return_type=ReturnType(
            data_type="basic", data_type_name="long", is_list=False
        ),
    )
    naming_sql = ResourceCandidate(
        candidate_id="naming_sql:BB_BILL_CUSTGRP:sql.by_invoice",
        kind="naming_sql",
        resource={"sql_name": "QUERY_BY_INVOICE"},
        bo_name="BB_BILL_CUSTGRP",
        return_type=ReturnType(
            data_type="bo", data_type_name="BB_BILL_CUSTGRP", is_list=False
        ),
        required_inputs=[invoice_input],
    )
    invoice_context = _candidate(
        "ctx.invoice_id", kind="context", type_name="long"
    )
    root = _goal("账单客户组名称")
    semantic = FakeSemantic(
        root,
        {
            ("账单客户组名称", ResourceTier.BO_FIELD): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=field.candidate_id,
                reason="target field",
            ),
            ("BB_BILL_CUSTGRP", ResourceTier.BO_ACCESS): CoverageDecision(
                kind=CoverageKind.DEPENDENCY_COVER,
                selected_candidate_id=naming_sql.candidate_id,
                missing_inputs=["INVOICE_ID"],
                reason="query returns target BO",
            ),
            ("INVOICE_ID", ResourceTier.VISIBLE_VALUE): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id="ctx.invoice_id",
                reason="context provides parameter",
            ),
        },
    )
    search = FakeSearch(
        {
            ("账单客户组名称", ResourceTier.BO_FIELD): [field],
            ("BB_BILL_CUSTGRP", ResourceTier.BO_ACCESS): [naming_sql],
            ("INVOICE_ID", ResourceTier.VISIBLE_VALUE): [invoice_context],
        }
    )

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "账单客户组"},
        query="查询账单客户组",
        expected_type=root.expected_type,
    )

    bo_resolution = result.root_resolution.dependencies[0]
    assert bo_resolution.candidate.candidate_id == naming_sql.candidate_id
    assert [item.candidate.candidate_id for item in bo_resolution.dependencies] == [
        "ctx.invoice_id"
    ]
    assert result.execution_order == [
        bo_resolution.dependencies[0].goal.goal_id,
        bo_resolution.goal.goal_id,
        "root",
    ]


def test_candidate_with_incompatible_type_is_not_sent_to_coverage_llm():
    wrong = _candidate("ctx.amount", type_name="decimal")
    semantic = FakeSemantic(
        _goal("客户名称"),
        {
            ("客户名称", ResourceTier.LITERAL): CoverageDecision(
                kind=CoverageKind.NOT_COVER,
                continue_search=False,
                reason="require a real resource",
            )
        },
    )
    literal = _candidate("literal:root", kind="literal")
    search = FakeSearch(
        {
            ("客户名称", ResourceTier.VISIBLE_VALUE): [wrong],
            ("客户名称", ResourceTier.LITERAL): [literal],
        }
    )

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "客户名称"},
        query="生成客户名称",
        expected_type=_goal("x").expected_type,
    )

    assert result.root_resolution is None
    assert [
        tier for _, tier, _ in semantic.coverage_calls
    ] == [ResourceTier.LITERAL]
    assert semantic.keyword_calls == ["root"]
    assert result.failed_goal_ids == ["root"]
    assert [
        tier for goal_name, tier in search.calls if goal_name == "客户名称"
    ] == [
        ResourceTier.VISIBLE_VALUE,
        ResourceTier.BO_FIELD,
        ResourceTier.FUNCTION,
        ResourceTier.LITERAL,
    ]


def test_failed_candidate_dependency_rolls_back_and_tries_next_candidate():
    bad = _candidate(
        "fn.bad",
        kind="function",
        inputs=[
            ResourceInput(
                name="MISSING",
                return_type=ReturnType(
                    data_type="basic", data_type_name="long", is_list=False
                ),
            )
        ],
    )
    good = _candidate("fn.good", kind="function")
    semantic = FakeSemantic(
        _goal("客户名称"),
        {
            ("客户名称", ResourceTier.FUNCTION): [
                CoverageDecision(
                    kind=CoverageKind.DEPENDENCY_COVER,
                    selected_candidate_id="fn.bad",
                    missing_inputs=["MISSING"],
                    reason="first candidate",
                ),
                CoverageDecision(
                    kind=CoverageKind.DIRECT_COVER,
                    selected_candidate_id="fn.good",
                    reason="fallback candidate",
                ),
            ]
        },
    )
    search = FakeSearch(
        {("客户名称", ResourceTier.FUNCTION): [bad, good]}
    )

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "客户名称"},
        query="生成客户名称",
        expected_type=_goal("x").expected_type,
    )

    assert result.root_resolution.candidate.candidate_id == "fn.good"
    assert any(item["action"] == "rollback" for item in result.resolution_trace)


def test_bo_field_creates_bo_access_dependency_before_commit():
    field = ResourceCandidate(
        candidate_id="bo.customer:field:NAME",
        kind="bo_field",
        resource={"bo": "BO_CUSTOMER"},
        bo_name="BO_CUSTOMER",
        field_name="NAME",
        return_type=ReturnType(
            data_type="basic", data_type_name="string", is_list=False
        ),
    )
    bo_object = ResourceCandidate(
        candidate_id="sql.customer",
        kind="naming_sql",
        resource={"sql": "query customer"},
        bo_name="BO_CUSTOMER",
        return_type=ReturnType(
            data_type="bo", data_type_name="BO_CUSTOMER", is_list=False
        ),
    )
    semantic = FakeSemantic(
        _goal("客户名称"),
        {
            ("客户名称", ResourceTier.BO_FIELD): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=field.candidate_id,
                reason="target field",
            ),
            ("BO_CUSTOMER", ResourceTier.BO_ACCESS): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=bo_object.candidate_id,
                reason="target BO",
            ),
        },
    )
    search = FakeSearch(
        {
            ("客户名称", ResourceTier.BO_FIELD): [field],
            ("BO_CUSTOMER", ResourceTier.BO_ACCESS): [bo_object],
        }
    )

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "客户名称"},
        query="生成客户名称",
        expected_type=_goal("x").expected_type,
    )

    assert result.root_resolution.candidate.candidate_id == field.candidate_id
    assert result.root_resolution.dependencies[0].goal.target_bo_name == "BO_CUSTOMER"
    bo_access_request = next(
        request for request in search.requests
        if request.goal.semantic_name == "BO_CUSTOMER"
        and request.tier == ResourceTier.BO_ACCESS
    )
    assert bo_access_request.target_bo_name == "BO_CUSTOMER"
    assert bo_access_request.target_field_name == "NAME"
    assert [
        request.tier
        for request in search.requests
        if request.goal.semantic_name == "BO_CUSTOMER"
    ] == [ResourceTier.BO_ACCESS]
    assert not any(
        request.tier == ResourceTier.BO_SELECT
        for request in search.requests
    )


def test_bo_field_falls_back_to_select_one_and_recursively_resolves_key():
    field = ResourceCandidate(
        candidate_id="bo.customer:field:NAME",
        kind="bo_field",
        resource={"bo": "BO_CUSTOMER"},
        bo_name="BO_CUSTOMER",
        field_name="NAME",
        return_type=ReturnType(
            data_type="basic", data_type_name="string", is_list=False
        ),
    )
    select_one = ResourceCandidate(
        candidate_id="select_one:BO_CUSTOMER:CUSTOMER_ID",
        kind="bo_select",
        resource={"bo": "BO_CUSTOMER"},
        bo_name="BO_CUSTOMER",
        field_name="NAME",
        return_type=ReturnType(
            data_type="bo", data_type_name="BO_CUSTOMER", is_list=False
        ),
        required_inputs=[
            ResourceInput(
                name="CUSTOMER_ID",
                return_type=ReturnType(
                    data_type="key", data_type_name="long", is_list=False
                ),
            )
        ],
        metadata={
            "operation": "select_one",
            "condition_fields": ["CUSTOMER_ID"],
        },
    )
    unsuitable_sql = ResourceCandidate(
        candidate_id="naming_sql:BO_CUSTOMER:by_status",
        kind="naming_sql",
        resource={"sql_name": "QUERY_BY_STATUS"},
        bo_name="BO_CUSTOMER",
        return_type=ReturnType(
            data_type="bo", data_type_name="BO_CUSTOMER", is_list=False
        ),
    )
    key_context = _candidate(
        "ctx.customer_id",
        kind="context",
        type_name="long",
    )
    semantic = FakeSemantic(
        _goal("客户名称"),
        {
            ("客户名称", ResourceTier.BO_FIELD): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=field.candidate_id,
                reason="target field",
            ),
            ("BO_CUSTOMER", ResourceTier.BO_ACCESS): CoverageDecision(
                kind=CoverageKind.NOT_COVER,
                continue_search=True,
                reason="NamingSQL conditions do not match query",
            ),
            ("BO_CUSTOMER", ResourceTier.BO_SELECT): CoverageDecision(
                kind=CoverageKind.DEPENDENCY_COVER,
                selected_candidate_id=select_one.candidate_id,
                missing_inputs=["CUSTOMER_ID"],
                reason="fallback by primary key",
            ),
            ("CUSTOMER_ID", ResourceTier.VISIBLE_VALUE): CoverageDecision(
                kind=CoverageKind.DIRECT_COVER,
                selected_candidate_id=key_context.candidate_id,
                reason="context provides primary key",
            ),
        },
    )
    search = FakeSearch(
        {
            ("客户名称", ResourceTier.BO_FIELD): [field],
            ("BO_CUSTOMER", ResourceTier.BO_ACCESS): [unsuitable_sql],
            ("BO_CUSTOMER", ResourceTier.BO_SELECT): [select_one],
            ("CUSTOMER_ID", ResourceTier.VISIBLE_VALUE): [key_context],
        }
    )

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "客户名称"},
        query="生成客户名称",
        expected_type=_goal("x").expected_type,
    )

    bo_resolution = result.root_resolution.dependencies[0]
    assert bo_resolution.candidate.kind == "bo_select"
    assert bo_resolution.candidate.metadata["operation"] == "select_one"
    assert bo_resolution.dependencies[0].candidate.candidate_id == "ctx.customer_id"
    assert bo_resolution.dependencies[0].goal.role == GoalRole.FILTER_VALUE
    assert (
        bo_resolution.bindings["CUSTOMER_ID"]
        == bo_resolution.dependencies[0].goal.goal_id
    )
    bo_tiers = [
        request.tier
        for request in search.requests
        if request.goal.semantic_name == "BO_CUSTOMER"
    ]
    assert bo_tiers == [ResourceTier.BO_ACCESS, ResourceTier.BO_SELECT]
