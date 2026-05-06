from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Any
from agent.resource_manager.loader.bo_loader import load_bo_registry_by_json
from agent.resource_manager.loader.context_loader import load_context_registry_by_json
from agent.resource_manager.loader.function_loader import load_function_registry_by_json
from agent.resource_manager.loader.local_context_loader import load_visible_local_context_registry
from agent.resource_manager.loader.registry_models import BoRegistry, ContextRegistry, FunctionRegistry, LocalContextRegistry


@dataclass(slots=True)
class LoadedResource:
    context_registry: Dict[str, ContextRegistry]
    bo_registry: Dict[str, BoRegistry]
    function_registry: Dict[str, FunctionRegistry]
    edsl_tree: Dict[str, Any]

    def get_visible_local_context_registry(self, node_path: str) -> Dict[str, LocalContextRegistry]:
        return {
            local_context.context_name: local_context
            for local_context in load_visible_local_context_registry(self.edsl_tree, node_path)
        }


class ResourceLoader:

    DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
    CONTEXT_FILE = "context_definition.json"
    BO_FILE = "bo_def_ootb.json"
    FUNCTION_FILE = "edsl_func.json"

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir is not None else self.DEFAULT_DATA_DIR
        self.context_registry_cache: Dict[str, Dict[str, ContextRegistry]] = {}
        self.bo_registry_cache: Dict[str, Dict[str, BoRegistry]] = {}
        self.function_registry_cache: Dict[str, Dict[str, FunctionRegistry]] = {}
    
    def load_resource(self, site_id: str, project_id: str, edsl_tree: Dict[str, Any]) -> LoadedResource:
        payload = self.get_resource_data(site_id, project_id)

        source_key = site_id + ":" + project_id
        if not self.context_registry_cache.get(source_key):
            self.context_registry_cache[source_key] = load_context_registry_by_json(payload.get("context") or {})
        if not self.bo_registry_cache.get(source_key):
            self.bo_registry_cache[source_key] = load_bo_registry_by_json(payload.get("bo") or {})
        if not self.function_registry_cache.get(source_key):
            self.function_registry_cache[source_key] = load_function_registry_by_json(payload.get("function") or {})

        return LoadedResource(
            context_registry=self.context_registry_cache[source_key],
            bo_registry=self.bo_registry_cache[source_key],
            function_registry=self.function_registry_cache[source_key],
            edsl_tree=edsl_tree,
        )

    def get_resource_data(self, site_id: str, project_id: str) -> Dict[str, Any]:
        return {
            "context": self._read_json_file(self.CONTEXT_FILE),
            "bo": self._read_json_file(self.BO_FILE),
            "function": self._read_json_file(self.FUNCTION_FILE),
        }

    def _read_json_file(self, file_name: str) -> Dict[str, Any]:
        file_path = self.data_dir / file_name
        if not file_path.exists():
            return {}
        
        with file_path.open("r", encoding="utf-8") as resource_file:
            data = json.load(resource_file)

        if not isinstance(data, dict):
            raise ValueError(f"Resource file must contain a JSON object: {file_path}")
        return data


resource_loader = ResourceLoader()
