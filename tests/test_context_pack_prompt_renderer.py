import json

from agent.context_pack.models import (
    ContextConflict, ContextFact, ContextItem, ContextPack, ContextSection,
    ContextWarning, SourceLocator,
)
from agent.context_pack.prompt_renderer import ContextPackPromptRenderer


def _item(index=0):
    return ContextItem(
        item_id=f"item-{index}", resource_name="dev_skill", item_type="recipe",
        authority="normative", content={"sql_command": "SELECT secret", "private": "hidden"},
        summary="customer name rule " + "x" * 20,
        locator=SourceLocator(source_id="skill", kind="heading", value=f"rule-{index}"),
        content_hash=f"hash-{index}", facts=[ContextFact(key="rule.name", value="concat")],
    )


def _pack():
    return ContextPack(
        status="partial", request_summary={"query": "name"}, current_node={"node_id": "n"},
        sections=[ContextSection(resource_name="dev_skill", status="ready", items=[_item(0)])],
        warnings=[ContextWarning(code="SAFE_CODE", message="private warning")],
        conflicts=[ContextConflict(fact_key="rule.name", item_ids=["item-0"],
                                   resolution="authoritative_wins", values=["secret value"])],
    )


def test_renderer_emits_stable_bounded_projection_without_private_content():
    rendered = ContextPackPromptRenderer().render_json(_pack())
    assert rendered == ContextPackPromptRenderer().render_json(_pack())
    value = json.loads(rendered)
    assert value["status"] == "partial"
    assert value["sections"][0]["items"][0]["facts"] == {"rule.name": "concat"}
    assert value["warnings"] == ["SAFE_CODE"]
    assert value["conflicts"] == [{"fact_key": "rule.name", "resolution": "authoritative_wins"}]
    assert "SELECT" not in rendered and "private" not in rendered and "secret value" not in rendered


def test_renderer_enforces_item_and_character_limits():
    pack = _pack()
    pack.sections[0].items.extend(_item(index) for index in range(1, 20))
    rendered = ContextPackPromptRenderer(max_items=2, max_chars=500).render_json(pack)
    value = json.loads(rendered)
    assert len(value["sections"][0]["items"]) <= 2
    assert len(rendered) <= 500
