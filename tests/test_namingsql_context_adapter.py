from copy import deepcopy

import pytest

from agent.context_manager.errors import ContextBuildError
from agent.context_pack.models import (
    ContextConflict,
    ContextFact,
    ContextItem,
    ContextPack,
    ContextSection,
    ContextTraceItem,
    ContextWarning,
    SourceLocator,
)
from agent.naming_sql_selector.context_adapter import NamingSqlContextAdapter


def _item(resource, authority, item_id, summary, facts=()):
    return ContextItem(
        item_id=item_id,
        resource_name=resource,
        item_type="test",
        authority=authority,
        content={"private": "not copied"},
        summary=summary,
        locator=SourceLocator(source_id=resource, kind="id", value=item_id),
        content_hash=item_id,
        facts=list(facts),
    )


def _pack(status="partial"):
    return ContextPack(
        status=status,
        request_summary={"query": "find customer fee"},
        current_node={"node_id": "n1"},
        sections=[
            ContextSection(resource_name="current_tree", status="ready", items=[
                _item("current_tree", "authoritative", "tree:field", "customer id field", [
                    ContextFact(key="field.customer_id.type", value="String")
                ])
            ]),
            ContextSection(resource_name="dev_skill", status="degraded", items=[
                _item("dev_skill", "normative", "skill:fee", "use customer id to find fees")
            ]),
            ContextSection(resource_name="ootb_edsl", status="ready", items=[
                _item("ootb_edsl", "reference", "ootb:fee", "reference fee lookup")
            ]),
        ],
        conflicts=[ContextConflict(
            fact_key="field.customer_id.type", item_ids=["tree:field", "skill:fee"],
            resolution="authoritative_wins", values=["String", "Long"],
        )],
        warnings=[ContextWarning(code="EMBEDDING_DEGRADED", message="private")],
        trace=[ContextTraceItem(source="dev_skill", action="trimmed", detail="budget")],
    )


def test_adapter_maps_authority_signals_warnings_and_does_not_mutate_pack():
    pack = _pack()
    snapshot = deepcopy(pack)

    result = NamingSqlContextAdapter().adapt(pack)

    assert result.query_terms == ["find", "customer", "fee"]
    assert result.authoritative_facts[0]["facts"] == {"field.customer_id.type": "String"}
    assert result.normative_rules[0]["summary"] == "use customer id to find fees"
    assert result.reference_examples[0]["item_id"] == "ootb:fee"
    assert "SECTION_DEGRADED:dev_skill" in result.warnings
    assert "PACK_WARNING:EMBEDDING_DEGRADED" in result.warnings
    assert "CONFLICT:field.customer_id.type:authoritative_wins" in result.warnings
    assert "TRACE:dev_skill:trimmed" in result.warnings
    assert pack == snapshot
    assert "private" not in str(result.model_dump())


def test_adapter_rejects_failed_pack():
    with pytest.raises(ContextBuildError) as raised:
        NamingSqlContextAdapter().adapt(_pack(status="failed"))
    assert raised.value.code == "CONTEXT_PACK_FAILED"


def test_adapter_enforces_item_and_character_bounds():
    pack = _pack(status="complete")
    pack.sections[0].items.extend(
        _item("current_tree", "authoritative", f"tree:{index}", "x" * 100)
        for index in range(5)
    )
    result = NamingSqlContextAdapter(max_items_per_section=2, max_chars=80).adapt(pack)
    assert len(result.authoritative_facts) == 1
    assert len(str(result.model_dump())) < 1000
    assert "CONTEXT_ADAPTER_TRIMMED" in result.warnings
