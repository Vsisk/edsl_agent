from dataclasses import dataclass

import pytest

from agent.context_pack.errors import ContextProviderError
from agent.context_pack.manager import ContextPackManager
from agent.context_pack.models import ContextPackRequest, ContextSection, ResourceName
from agent.context_pack.project_context import ProjectContext
from agent.context_pack.registry import RecallProfile, SourceRegistry


class CapturingProvider:
    def __init__(self, resource_name, error=None):
        self.resource_name = resource_name
        self.error = error
        self.calls = []

    def retrieve(self, request, project_context, profile):
        self.calls.append((request, project_context, profile))
        if self.error:
            raise self.error
        return ContextSection(resource_name=self.resource_name, status="empty")


class CapturingBuilder:
    def __init__(self):
        self.calls = []

    def build(self, request, sections):
        self.calls.append((request, sections))
        return sections


def request(resources):
    return ContextPackRequest(node={"node_id": "n"}, query="q", resource_names=resources)


def test_manager_invokes_only_requested_provider():
    dev = CapturingProvider(ResourceName.DEV_SKILL)
    tree = CapturingProvider(ResourceName.CURRENT_TREE)
    builder = CapturingBuilder()
    manager = ContextPackManager(SourceRegistry([dev, tree]), builder)

    result = manager.build(request(["dev_skill"]), ProjectContext())

    assert len(dev.calls) == 1
    assert tree.calls == []
    assert [section.resource_name for section in result] == [ResourceName.DEV_SKILL]


def test_registry_uses_canonical_order_not_request_order():
    dev = CapturingProvider(ResourceName.DEV_SKILL)
    tree = CapturingProvider(ResourceName.CURRENT_TREE)
    manager = ContextPackManager(SourceRegistry([dev, tree]), CapturingBuilder())

    result = manager.build(request(["dev_skill", "current_tree"]), ProjectContext())

    assert [section.resource_name for section in result] == [ResourceName.CURRENT_TREE, ResourceName.DEV_SKILL]


def test_registry_rejects_duplicate_provider_names():
    with pytest.raises(ValueError, match="duplicate provider"):
        SourceRegistry([CapturingProvider(ResourceName.DEV_SKILL), CapturingProvider(ResourceName.DEV_SKILL)])


def test_expected_provider_error_becomes_sanitized_error_section():
    dev = CapturingProvider(ResourceName.DEV_SKILL, ContextProviderError("SKILL_INVALID", "bad markdown"))
    manager = ContextPackManager(SourceRegistry([dev]), CapturingBuilder())

    [section] = manager.build(request(["dev_skill"]), ProjectContext())

    assert section.status.value == "error"
    assert section.warnings[0].code == "SKILL_INVALID"
    assert section.warnings[0].message == "bad markdown"


def test_unexpected_provider_exception_is_not_hidden():
    dev = CapturingProvider(ResourceName.DEV_SKILL, RuntimeError("programming defect"))
    manager = ContextPackManager(SourceRegistry([dev]), CapturingBuilder())

    with pytest.raises(RuntimeError, match="programming defect"):
        manager.build(request(["dev_skill"]), ProjectContext())


def test_manager_passes_configured_profile():
    dev = CapturingProvider(ResourceName.DEV_SKILL)
    profile = RecallProfile(max_items=2, max_chars=500)
    manager = ContextPackManager(
        SourceRegistry([dev]), CapturingBuilder(), profiles={ResourceName.DEV_SKILL: profile}
    )

    manager.build(request(["dev_skill"]), ProjectContext())

    assert dev.calls[0][2] == profile
