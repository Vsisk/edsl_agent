from agent.context_pack.builder import ContextPackBuilder
from agent.context_pack.models import (
    ContextFact,
    ContextItem,
    ContextPackRequest,
    ContextSection,
    RetrievalEvidence,
    SourceLocator,
)


def request(resources=("dev_skill", "current_tree")):
    return ContextPackRequest(node={"node_id": "n"}, query="q", resource_names=list(resources))


def item(item_id, resource, authority, *, fact_value=None, exact=False, size=10, rank=1):
    facts = [] if fact_value is None else [ContextFact(key="customer.name.type", value=fact_value)]
    evidence = [RetrievalEvidence(
        source=resource, action="recall", reason="match", match_kind="exact" if exact else "fused"
    )]
    return ContextItem(
        item_id=item_id,
        resource_name=resource,
        item_type="fact",
        authority=authority,
        content={"text": "x" * size},
        summary=item_id,
        locator=SourceLocator(source_id=resource, kind="id", value=item_id),
        evidence=evidence,
        content_hash=f"hash-{item_id}",
        facts=facts,
        rank=rank,
    )


def section(resource, status="ready", items=None):
    return ContextSection(resource_name=resource, status=status, items=items or [])


def test_builder_uses_canonical_order_and_detects_authority_conflict():
    dev = item("rule", "dev_skill", "normative", fact_value="Text")
    tree = item("field", "current_tree", "authoritative", fact_value="String")

    pack = ContextPackBuilder().build(
        request(), [section("dev_skill", items=[dev]), section("current_tree", items=[tree])]
    )

    assert [value.resource_name.value for value in pack.sections] == ["current_tree", "dev_skill"]
    assert pack.conflicts[0].fact_key == "customer.name.type"
    assert pack.conflicts[0].resolution == "authoritative_wins"
    assert pack.status.value == "complete"


def test_builder_preserves_exact_and_authoritative_items_under_limits():
    reference = item("reference", "ootb_edsl", "reference", rank=1)
    exact_rule = item("exact-rule", "dev_skill", "normative", exact=True, rank=2)
    fact = item("fact", "current_tree", "authoritative", rank=3)
    builder = ContextPackBuilder(max_items_by_resource={"dev_skill": 1}, global_max_chars=10000)

    pack = builder.build(
        request(("dev_skill", "current_tree", "ootb_edsl")),
        [section("dev_skill", items=[reference.model_copy(update={"resource_name": "dev_skill"}), exact_rule]),
         section("current_tree", items=[fact]), section("ootb_edsl", items=[reference])],
    )

    assert [value.item_id for value in pack.sections[1].items] == ["exact-rule"]
    assert any(trace.action == "trimmed" for trace in pack.trace)


def test_builder_returns_partial_with_ready_content_and_failed_without_items():
    ready = section("dev_skill", items=[item("rule", "dev_skill", "normative")])
    unavailable = section("ootb_edsl", status="unavailable")

    partial = ContextPackBuilder().build(request(("dev_skill", "ootb_edsl")), [ready, unavailable])
    failed = ContextPackBuilder().build(request(("ootb_edsl",)), [unavailable])

    assert partial.status.value == "partial"
    assert partial.sections[0].items[0].item_id == "rule"
    assert failed.status.value == "failed"
    assert failed.current_node == {"node_id": "n"}


def test_builder_rejects_item_from_wrong_resource():
    wrong = item("wrong", "current_tree", "authoritative")
    try:
        ContextPackBuilder().build(request(("dev_skill",)), [section("dev_skill", items=[wrong])])
    except ValueError as error:
        assert "resource mismatch" in str(error)
    else:
        raise AssertionError("expected resource mismatch")
