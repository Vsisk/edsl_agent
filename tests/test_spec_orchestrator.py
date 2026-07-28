from agent.resource_manager.loader.registry_models import ReturnType
from agent.spec_orchestration.models import (
    CoverageDecision,
    CoverageKind,
    GoalRole,
    ResourceCandidate,
    ResourceInput,
    ResourceTier,
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

    def generate_goal(self, **_):
        return self.root_goal.model_copy(deep=True)

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


def test_naming_sql_is_committed_only_after_parameter_goal_resolves():
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
    root = ValueGoal(
        goal_id="root",
        semantic_name="账单客户组",
        role=GoalRole.INTERMEDIATE_VALUE,
        expected_type=ReturnType(
            data_type="bo", data_type_name="BB_BILL_CUSTGRP", is_list=False
        ),
        target_bo_name="BB_BILL_CUSTGRP",
    )
    semantic = FakeSemantic(
        root,
        {
            ("账单客户组", ResourceTier.BO_ACCESS): CoverageDecision(
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
            ("账单客户组", ResourceTier.BO_ACCESS): [naming_sql],
            ("INVOICE_ID", ResourceTier.VISIBLE_VALUE): [invoice_context],
        }
    )

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "账单客户组"},
        query="查询账单客户组",
        expected_type=root.expected_type,
    )

    assert result.root_resolution.candidate.candidate_id == naming_sql.candidate_id
    assert [item.candidate.candidate_id for item in result.root_resolution.dependencies] == [
        "ctx.invoice_id"
    ]
    assert result.execution_order == [
        result.root_resolution.dependencies[0].goal.goal_id,
        "root",
    ]


def test_candidate_with_incompatible_type_is_not_sent_to_coverage_llm():
    wrong = _candidate("ctx.amount", type_name="decimal")
    semantic = FakeSemantic(_goal("客户名称"), {})
    search = FakeSearch({("客户名称", ResourceTier.VISIBLE_VALUE): [wrong]})

    result = SpecOrchestrator(semantic=semantic, search=search).resolve(
        node_info={"node_name": "客户名称"},
        query="生成客户名称",
        expected_type=_goal("x").expected_type,
    )

    assert result.root_resolution is None
    assert semantic.coverage_calls == []
    assert semantic.keyword_calls == ["root"]
    assert result.failed_goal_ids == ["root"]


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
    assert bo_tiers.index(ResourceTier.BO_ACCESS) < bo_tiers.index(
        ResourceTier.BO_SELECT
    )
