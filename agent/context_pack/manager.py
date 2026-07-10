from collections.abc import Mapping
from typing import Any

from agent.context_pack.errors import ContextProviderError
from agent.context_pack.models import (ContextPackRequest, ContextSection, ContextWarning,
                                       ResourceName, SectionStatus)
from agent.context_pack.project_context import ProjectContext
from agent.context_pack.registry import RecallProfile, SourceRegistry


DEFAULT_PROFILES = {
    ResourceName.CURRENT_TREE: RecallProfile(max_items=10, max_chars=12000),
    ResourceName.NAMINGSQL: RecallProfile(max_items=5, max_chars=10000),
    ResourceName.DEV_SKILL: RecallProfile(max_items=3, max_chars=8000),
    ResourceName.OOTB_EDSL: RecallProfile(max_items=3, max_chars=12000),
}


class ContextPackManager:
    def __init__(
        self,
        registry: SourceRegistry,
        builder: Any,
        profiles: Mapping[ResourceName, RecallProfile] | None = None,
    ) -> None:
        self.registry = registry
        self.builder = builder
        self.profiles = {**DEFAULT_PROFILES, **dict(profiles or {})}

    def build(self, request: ContextPackRequest, project_context: ProjectContext):
        sections = []
        for provider in self.registry.requested(request.resource_names):
            try:
                section = provider.retrieve(
                    request,
                    project_context,
                    self.profiles[provider.resource_name],
                )
            except ContextProviderError as exc:
                section = ContextSection(
                    resource_name=provider.resource_name,
                    status=SectionStatus.ERROR,
                    warnings=[ContextWarning(code=exc.code, message=exc.safe_detail)],
                )
            sections.append(section)
        return self.builder.build(request, sections)
