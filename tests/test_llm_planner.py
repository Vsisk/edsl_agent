import json

import pytest

from agent.context_manager.models import (ContextRequirementHint, NamingSqlCandidate,
    NamingSqlSelectionConstraints)
from agent.environment.environment import FilteredEnvironment
from agent.llm.prompt_manager import prompt_manager
from agent.models import NodeDef
from agent.naming_sql_selector import NamingSqlSelectResponse
from agent.planner.llm_planner import LLMPlanner, _summarize_filtered_environment_json


class Settings:
    def model_for(self, name): return name


class Client:
    is_usable = True
    settings = Settings()
    def __init__(self, *responses): self.responses, self.calls = list(responses), []
    def complete(self, **payload): self.calls.append(payload); return self.responses.pop(0)


class R:
    def __init__(self, **values): self.__dict__.update(values)


def candidate(cid, name, rank):
    return NamingSqlCandidate(candidate_id=f"internal:{cid}", bo_name="Customer", naming_sql_id=cid,
        naming_sql_name=name, annotation="safe", param_list=[{"param_name": "id", "data_type_name": "String"}],
        return_type={"data_type_name": "Customer"}, source="resource_registry", rank=rank,
        evidence=[f"evidence {rank}"])


def selection():
    return NamingSqlSelectResponse(success=True, candidates=[candidate("sql.1", "FindCustomer", 1),
        candidate("sql.2", "FindCustomerRecent", 2)],
        context_requirements_hint=[ContextRequirementHint(semantic_name="customer id", source_hint="context")],
        selection_constraints=NamingSqlSelectionConstraints(allowed_bo_names=["Customer"],
            allowed_naming_sql_ids=["sql.1", "sql.2"], max_candidates=2))


def test_summary_exposes_only_top_k_and_never_sql_body_sibling_or_internal_candidate_id():
    bo = R(resource_id="bo", bo_name="Customer", bo_desc="", property_list=[], naming_sql_list=[
        R(sql_name="SiblingSql", sql_description="SELECT secret", param_list=[])])
    decoded = json.loads(_summarize_filtered_environment_json(FilteredEnvironment(
        selected_bos=[bo], naming_sql_selection=selection())))
    rendered = json.dumps(decoded, ensure_ascii=False)
    assert [item["name"] for item in decoded["naming_sql_selection"]["candidates"]] == ["FindCustomer", "FindCustomerRecent"]
    assert "hints" in decoded["naming_sql_selection"] and "constraints" in decoded["naming_sql_selection"]
    assert "SiblingSql" not in rendered and "SELECT secret" not in rendered and "internal:" not in rendered


def test_repair_path_revalidates_top_k_membership():
    old = prompt_manager._prompts
    prompt_manager._prompts = {"planner": {"zh": "{{resources_json}}"}, "planner_repair": {"zh": "{{resources_json}} {{invalid_plan_json}} {{error_message}}"}}
    try:
        client = Client('{"nodes":[{"type":"fetch","name":"Outside","params":[]}]}',
            '{"nodes":[{"type":"fetch","name":"StillOutside","params":[]}]}')
        with pytest.raises(ValueError, match="NAMING_SQL_OUTSIDE_TOP_K"):
            LLMPlanner(client).plan(node_info=NodeDef(node_id="x", node_path="$.x", node_name="x"),
                user_query="x", filtered_env=FilteredEnvironment(naming_sql_selection=selection()))
        assert len(client.calls) == 2
    finally:
        prompt_manager._prompts = old


def test_control_characters_are_rejected():
    value = selection(); value.candidates[0].evidence = ["bad\ntext"]
    with pytest.raises(ValueError, match="NAMING_SQL_SELECTION_TOO_LARGE"):
        _summarize_filtered_environment_json(FilteredEnvironment(naming_sql_selection=value))
