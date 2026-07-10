from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from agent.resource_manager.loader.resource_loader import LoadedResource


@dataclass(frozen=True, slots=True)
class ProjectContext:
    current_tree: dict[str, Any] | None = None
    ootb_tree: dict[str, Any] | None = None
    dev_skill_path: Path | None = None
    loaded_resource: "LoadedResource | None" = None
    source_versions: Mapping[str, str] = field(default_factory=dict)
