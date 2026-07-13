"""Unified local context-pack construction."""

from .builder import ContextPackBuilder
from .manager import ContextPackManager
from .models import ContextPack, ContextPackRequest, ResourceName
from .project_context import ProjectContext
from .providers import CurrentTreeProvider, DevSkillProvider, OotbEdslProvider
from .registry import SourceRegistry
from .search import LocalResourceSearchTool
from .resource_router import ContextResourceRoute, FastContextResourceRouter


def create_context_pack_manager(*, embedding_client=None, profiles=None) -> ContextPackManager:
    search = LocalResourceSearchTool(embedding_client=embedding_client)
    registry = SourceRegistry([
        CurrentTreeProvider(search),
        DevSkillProvider(search),
        OotbEdslProvider(search),
    ])
    return ContextPackManager(registry, ContextPackBuilder(), profiles=profiles)


__all__ = [
    "ContextPack",
    "ContextPackManager",
    "ContextPackRequest",
    "ContextResourceRoute",
    "FastContextResourceRouter",
    "ProjectContext",
    "ResourceName",
    "create_context_pack_manager",
]
