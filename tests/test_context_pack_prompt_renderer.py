import json
from copy import deepcopy

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


def test_renderer_projects_complete_current_tree_node_without_children_or_mutation():
    canonical_node = {
        "node_id": "customer-name",
        "tree_node_type": "simple_leaf",
        "data_expression": {"expression": "$ctx$.customer.name"},
        "edsl_semi_struct": {"operator": "property"},
        "custom_config": {"enabled": True},
        "children": [{"node_id": "nested", "data_expression": {"expression": "hidden"}}],
    }
    item = ContextItem(
        item_id="current-field",
        resource_name="current_tree",
        item_type="field",
        authority="authoritative",
        content={"value": canonical_node, "json_path": "$.children[0]"},
        summary="customer name",
        locator=SourceLocator(source_id="current-tree", kind="json_path", value="$.children[0]"),
        content_hash="current-hash",
    )
    pack = ContextPack(
        status="complete",
        request_summary={"query": "customer name"},
        current_node={"node_id": "customer-name"},
        sections=[ContextSection(resource_name="current_tree", status="ready", items=[item])],
    )
    original = deepcopy(item.content["value"])

    rendered_item = json.loads(ContextPackPromptRenderer().render_json(pack))["sections"][0]["items"][0]

    assert rendered_item["node"] == {
        "node_id": "customer-name",
        "tree_node_type": "simple_leaf",
        "data_expression": {"expression": "$ctx$.customer.name"},
        "edsl_semi_struct": {"operator": "property"},
        "custom_config": {"enabled": True},
    }
    assert item.content["value"] == original


def test_renderer_keeps_non_node_items_compact():
    pack = _pack()
    local_item = ContextItem(
        item_id="current-local",
        resource_name="current_tree",
        item_type="local",
        authority="authoritative",
        content={"value": {"property_name": "customer"}},
        summary="customer",
        locator=SourceLocator(source_id="current-tree", kind="json_path", value="$.local_context[0]"),
        content_hash="local-hash",
    )
    pack.sections.append(ContextSection(resource_name="current_tree", status="ready", items=[local_item]))

    sections = json.loads(ContextPackPromptRenderer().render_json(pack))["sections"]

    assert "node" not in sections[0]["items"][0]
    assert "node" not in sections[1]["items"][0]


def test_renderer_drops_oversized_node_atomically_and_reports_trimming():
    item = ContextItem(
        item_id="oversized-node",
        resource_name="current_tree",
        item_type="node",
        authority="authoritative",
        content={"value": {"node_id": "large", "data_expression": {"expression": "x" * 1000}}},
        summary="large node",
        locator=SourceLocator(source_id="current-tree", kind="json_path", value="$.children[0]"),
        content_hash="large-hash",
    )
    pack = ContextPack(
        status="complete",
        request_summary={"query": "large"},
        current_node={"node_id": "large"},
        sections=[ContextSection(resource_name="current_tree", status="ready", items=[item])],
    )

    rendered = ContextPackPromptRenderer(max_chars=500).render_json(pack)
    value = json.loads(rendered)

    assert value["sections"][0]["items"] == []
    assert "CONTEXT_PACK_PROMPT_TRIMMED" in value["warnings"]
    assert "x" * 1000 not in rendered
