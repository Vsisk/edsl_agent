from dataclasses import dataclass
from typing import Protocol

from agent.context_pack.errors import RESOURCE_NOT_REGISTERED, ContextProviderError
from agent.context_pack.models import ContextPackRequest, ContextSection, ResourceName
from agent.context_pack.project_context import ProjectContext


@dataclass(frozen=True, slots=True)
class RecallProfile:
    max_items: int = 5
    max_chars: int = 8000


class ContextProviderProtocol(Protocol):
    resource_name: ResourceName

    def retrieve(
        self,
        request: ContextPackRequest,
        project_context: ProjectContext,
        profile: RecallProfile,
    ) -> ContextSection: ...


CANONICAL_RESOURCE_ORDER = (
    ResourceName.CURRENT_TREE,
    ResourceName.DEV_SKILL,
    ResourceName.OOTB_EDSL,
)


class SourceRegistry:
    def __init__(self, providers: list[ContextProviderProtocol]) -> None:
        self._providers = {}
        for provider in providers:
            if provider.resource_name in self._providers:
                raise ValueError(f"duplicate provider: {provider.resource_name.value}")
            self._providers[provider.resource_name] = provider

    def requested(self, resource_names: list[ResourceName]) -> list[ContextProviderProtocol]:
        requested = set(resource_names)
        missing = [name for name in resource_names if name not in self._providers]
        if missing:
            raise ContextProviderError(RESOURCE_NOT_REGISTERED, missing[0].value)
        return [self._providers[name] for name in CANONICAL_RESOURCE_ORDER if name in requested]
