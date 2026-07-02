from __future__ import annotations

from enum import Enum
from typing import Any

from agent.context_manager.models import ContextAsset
from agent.context_manager.errors import ContextBuildError, INVALID_LLM_OUTPUT
from agent.context_manager.models import ContextEvidenceItem, NamingSqlCandidate, NamingSqlResourceCandidates
from agent.resource_manager.models import (
    BoRegistry,
    ContextRegistry,
    FunctionRegistry,
    LocalContextRegistry,
    NamingSqlDefTerm,
    PropertyTerm,
)


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return "" if value is None else str(value)


def _labeled(**parts: Any) -> str:
    return "; ".join(f"{label}: {_value(value)}" for label, value in parts.items() if value not in (None, "", []))


class _ResourceAssetBase:
    """Pure conversion from authoritative resource registries to semantic assets."""

    source = "resource_registry"

    def bo(self, registry: BoRegistry) -> ContextAsset:
        fields = ", ".join(
            _labeled(name=item.field_name, description=item.description, type=item.data_type_name, list=item.is_list)
            for item in registry.property_list
        )
        return ContextAsset(
            asset_id=f"bo:{registry.bo_name}", asset_type="bo", scope="global",
            content=registry.model_dump(mode="json"),
            index_text=_labeled(resource="business object", name=registry.bo_name, description=registry.bo_desc, fields=fields),
            source=self.source,
        )


class ResourceAssetBuilder(_ResourceAssetBase):
    """Recall and rerank NamingSQL plus supporting resource assets."""

    def __init__(self, retriever: Any = None, reranker: Any = None,
                 asset_builder: ResourceAssetBuilder | None = None) -> None:
        self.retriever, self.reranker = retriever, reranker
        self.asset_builder = asset_builder or self

    def resolve(self, request: Any, loaded_resource: Any, node_block: Any,
                logic_block: Any = None) -> NamingSqlResourceCandidates:
        assets = self._assets(loaded_resource)
        recalled = self.retriever.retrieve(request.query, assets, semantic_limit=max(request.top_k, 10)) if self.retriever else assets
        recalled = self._canonical(recalled, assets, "retriever")
        selected, extra_evidence = recalled, []
        if self.reranker:
            result = self.reranker.rerank(request.query, recalled, {"node": node_block, "logic": logic_block})
            selected = self._canonical(getattr(result, "selected_assets", None), recalled, "reranker")
            extra_evidence = list(getattr(result, "evidence_trace", []) or [])
        sql_assets = [asset for asset in selected if asset.asset_type == "naming_sql"]
        candidates = [self._candidate(asset) for asset in sql_assets]
        evidence = [ContextEvidenceItem(source="resource_registry", action="candidate_recalled",
            asset_id=asset.asset_id, evidence="Recalled canonical NamingSQL candidate") for asset in sql_assets]
        return NamingSqlResourceCandidates(candidates=candidates, evidence=evidence + extra_evidence)

    def _assets(self, loaded: Any) -> list[ContextAsset]:
        result: list[ContextAsset] = []
        for bo in getattr(loaded, "bo_registry", {}).values():
            result.append(self.asset_builder.bo(bo))
            result.extend(self.asset_builder.bo_field(bo.bo_name, field) for field in bo.property_list)
            result.extend(self.asset_builder.naming_sql(bo.bo_name, sql, bo) for sql in bo.naming_sql_list)
        result.extend(self.asset_builder.context(item) for item in getattr(loaded, "context_registry", {}).values())
        result.extend(self.asset_builder.function(item) for item in getattr(loaded, "function_registry", {}).values())
        return result

    @staticmethod
    def _canonical(returned: Any, originals: list[ContextAsset], source: str) -> list[ContextAsset]:
        if not isinstance(returned, (list, tuple)):
            raise ContextBuildError(INVALID_LLM_OUTPUT, f"{source} returned malformed assets")
        by_id = {item.asset_id: item for item in originals}
        result, seen = [], set()
        for item in returned:
            if not isinstance(item, ContextAsset) or item.asset_id not in by_id or item.asset_id in seen:
                raise ContextBuildError(INVALID_LLM_OUTPUT, f"{source} returned noncanonical assets")
            seen.add(item.asset_id); result.append(by_id[item.asset_id])
        return result

    @staticmethod
    def _candidate(asset: ContextAsset) -> NamingSqlCandidate:
        content = asset.content
        sql_id = str(content.get("naming_sql_id") or content.get("resource_id") or asset.asset_id.split(":")[-1])
        return NamingSqlCandidate(candidate_id=asset.asset_id, bo_name=str(content.get("bo_name") or ""),
            naming_sql_id=sql_id, naming_sql_name=content.get("sql_name") or content.get("naming_sql_name"),
            annotation=str(content.get("sql_description") or content.get("annotation") or ""),
            param_list=list(content.get("param_list") or []),
            return_type=content.get("return_type"),
            source="resource_registry", rank=0, evidence=[asset.index_text],
            retrieval_metadata=dict(asset.metadata))

    def bo_field(self, bo_name: str, field: PropertyTerm) -> ContextAsset:
        return ContextAsset(
            asset_id=f"bo_field:{bo_name}:{field.field_name}", asset_type="bo_field", scope="global",
            content={"bo_name": bo_name, **field.model_dump(mode="json")},
            index_text=_labeled(resource="business object field", bo=bo_name, name=field.field_name, description=field.description, type=field.data_type_name, data_category=field.data_type, list=field.is_list),
            source=self.source,
        )

    def naming_sql(self, bo_name: str, definition: NamingSqlDefTerm,
                   bo_registry: BoRegistry | None = None) -> ContextAsset:
        params = ", ".join(
            _labeled(name=item.param_name, type=item.data_type_name, data_category=item.data_type, list=item.is_list)
            for item in definition.param_list
        )
        bo_description = bo_registry.bo_desc if bo_registry is not None else None
        bo_tags = list(bo_registry.tag) if bo_registry is not None else []
        field_facts = [
            {"field_name": field.field_name, "description": field.description,
             "data_type": _value(field.data_type), "data_type_name": field.data_type_name,
             "is_list": field.is_list}
            for field in (bo_registry.property_list if bo_registry is not None else [])
        ]
        content = {"bo_name": bo_name, **definition.model_dump(mode="json")}
        if bo_registry is not None:
            content.update({"bo_description": bo_description, "bo_tags": bo_tags,
                            "bo_field_facts": field_facts})
        return ContextAsset(
            asset_id=f"naming_sql:{bo_name}:{definition.naming_sql_id}", asset_type="naming_sql", scope="global",
            content=content,
            index_text=_labeled(resource="NamingSQL", bo=bo_name,
                bo_description=bo_description, suitable_scenarios=definition.sql_description,
                tags=", ".join(bo_tags), id=definition.naming_sql_id,
                name=definition.sql_name, purpose=definition.sql_description,
                label=definition.label_name, parameters=params,
                bo_field_facts=", ".join(_labeled(name=f["field_name"],
                    description=f["description"], type=f["data_type_name"], list=f["is_list"])
                    for f in field_facts)),
            source=self.source,
        )

    def context(self, registry: ContextRegistry | LocalContextRegistry) -> ContextAsset:
        property_type = _value(registry.property_type).lower()
        path = registry.context_name
        is_iter = property_type == "iter" or path.startswith(("$iter$", "it."))
        if is_iter:
            asset_type, scope = "iter_context", "node"
        elif isinstance(registry, LocalContextRegistry) or property_type == "local" or path.startswith("$local$"):
            asset_type, scope = "local_context", "node"
        else:
            asset_type, scope = "global_context", "global"
        return_type = registry.return_type
        return ContextAsset(
            asset_id=f"context:{registry.resource_id}", asset_type=asset_type, scope=scope,
            content=registry.model_dump(mode="json"),
            index_text=_labeled(resource=asset_type.replace("_", " "), path=path, annotation=registry.annotation, return_type=getattr(return_type, "data_type", None), return_type_name=getattr(return_type, "data_type_name", None), list=getattr(return_type, "is_list", None), source_path=getattr(registry, "source_path", None)),
            source=self.source,
        )

    def function(self, registry: FunctionRegistry) -> ContextAsset:
        params = ", ".join(
            _labeled(name=item.param_name, type=item.data_type_name, data_category=item.data_type, list=item.is_list)
            for item in registry.param_list
        )
        function_id = f"function:{registry.func_class}:{registry.func_name}" if registry.func_class else f"function:{registry.func_name}"
        return ContextAsset(
            asset_id=function_id, asset_type="function", scope="global",
            content=registry.model_dump(mode="json"),
            index_text=_labeled(resource="function", class_name=registry.func_class, name=registry.func_name, description=registry.func_desc, parameters=params, return_type=registry.return_type.data_type_name, return_category=registry.return_type.data_type, return_list=registry.return_type.is_list),
            source=self.source,
        )


class ResourceContextResolver(ResourceAssetBuilder):
    """Public resolver with the standard hybrid-recall and LLM-rerank pipeline."""

    def __init__(self, retriever: Any = None, reranker: Any = None,
                 asset_builder: ResourceAssetBuilder | None = None) -> None:
        if retriever is None:
            from agent.context_manager.retrieval import EmbeddingClient, HybridRetriever
            retriever = HybridRetriever(EmbeddingClient())
        if reranker is None:
            from agent.context_manager.retrieval import LLMReranker
            reranker = LLMReranker()
        super().__init__(retriever, reranker, asset_builder or ResourceAssetBuilder())
