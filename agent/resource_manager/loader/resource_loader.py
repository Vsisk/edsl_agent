from dataclasses import dataclass
from typing import Dict, Any
from agent.resource_manager.loader.context_loader import load_context_registry_by_json
from agent.resource_manager.models import BoRegistry, ContextRegistry, FunctionRegistry


@dataclass(slots=True)
class LoadedResource:
    context_registry: Dict[str, ContextRegistry]
    bo_registry: Dict[str, BoRegistry]
    function_registry: Dict[str, FunctionRegistry]
    edsl_tree: Dict[str, Any]


class ResourceLoader:

    def __init__(self):
        self.context_registry_cache: Dict[str, Dict[str, ContextRegistry]] = {}
        self.bo_registry_cache: Dict[str, Dict[str, BoRegistry]] = {}
        self.function_registry_cache: Dict[str, Dict[str, FunctionRegistry]] = {}
    
    def load_resource(self, site_id: str, project_id: str, edsl_tree: Dict[str, Any]):
        payload = self.get_resource_data(site_id, project_id)

        source_key = site_id + ":" + project_id
        if not self.context_registry_cache.get(source_key):
            context_registry = load_context_registry_by_json(payload.get("context") or {})
        
