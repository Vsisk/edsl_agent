from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.context_pack.models import (
    Authority,
    ContextFact,
    ContextItem,
    ContextPack,
    ContextPackRequest,
    ContextSection,
    PackStatus,
    RetrievalEvidence,
    ResourceName,
    SectionStatus,
    SourceLocator,
)


def test_request_has_core_fields_and_deduplicates_resources():
    request = ContextPackRequest(
        node={"node_id": "n1"},
        query="  生成客户姓名  ",
        resource_names=["dev_skill", "current_tree", "dev_skill"],
    )

    assert request.query == "生成客户姓名"
    assert request.resource_names == [ResourceName.DEV_SKILL, ResourceName.CURRENT_TREE]
    assert set(request.model_dump()) == {"node", "query", "resource_names", "system_context"}
    assert request.system_context == {}


def test_request_and_pack_accept_system_context_for_downstream_generation():
    system_context = {
        "business_path": ["Bill", "AcctInfo"],
        "business_path_text": "Bill/AcctInfo",
        "business_level": "acct",
    }

    request = ContextPackRequest(
        node={"node_id": "n1"},
        query="account balance",
        resource_names=["dev_skill"],
        system_context=system_context,
    )
    pack = ContextPack(
        status=PackStatus.COMPLETE,
        request_summary={"query": request.query},
        current_node=request.node,
        system_context=request.system_context,
    )

    assert request.system_context == system_context
    assert pack.system_context == system_context


@pytest.mark.parametrize(
    "payload",
    [
        {"node": {}, "query": "x", "resource_names": ["dev_skill"]},
        {"node": {"node_id": "n"}, "query": " ", "resource_names": ["dev_skill"]},
        {"node": {"node_id": "n"}, "query": "x", "resource_names": []},
        {"node": {"node_id": "n"}, "query": "x", "resource_names": ["unknown"]},
        {"node": {"node_id": "n"}, "query": "x", "resource_names": ["dev_skill"], "extra": True},
    ],
)
def test_request_rejects_invalid_payload(payload):
    with pytest.raises(ValidationError):
        ContextPackRequest(**payload)


def test_request_rejects_namingsql_as_a_context_resource():
    with pytest.raises(ValidationError):
        ContextPackRequest(
            node={"node_id": "n"},
            query="find customer",
            resource_names=["namingsql"],
        )


def make_item(item_id="item-1"):
    return ContextItem(
        item_id=item_id,
        resource_name="current_tree",
        item_type="field",
        authority="authoritative",
        content={"name": "customerName"},
        summary="customer name",
        locator=SourceLocator(source_id="current-tree", kind="json_path", value="$.children[0]"),
        evidence=[],
        content_hash="abc123",
        facts=[ContextFact(key="field.customerName.type", value="String")],
    )


def test_pack_models_use_independent_defaults_and_enum_values():
    first = ContextSection(resource_name="current_tree", status="ready", items=[make_item()])
    second = ContextSection(resource_name="dev_skill", status="empty")
    first.evidence.append(RetrievalEvidence(source="current-tree", action="exact", reason="name"))

    pack = ContextPack(
        status=PackStatus.PARTIAL,
        request_summary={"query": "customer"},
        current_node={"node_id": "n1"},
        sections=[first, second],
    )

    assert second.evidence == []
    assert pack.sections[0].items[0].authority is Authority.AUTHORITATIVE
    assert pack.sections[1].status is SectionStatus.EMPTY
    assert pack.model_dump(mode="json")["status"] == "partial"


def test_pack_models_reject_extra_fields_and_require_locator_hash():
    with pytest.raises(ValidationError):
        SourceLocator(source_id="tree", kind="json_path", value="$", path=Path("x"), extra=True)
    payload = make_item().model_dump()
    payload["content_hash"] = ""
    with pytest.raises(ValidationError):
        ContextItem(**payload)
