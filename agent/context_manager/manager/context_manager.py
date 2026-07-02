from __future__ import annotations

from typing import Any

from agent.context_manager.errors import ContextBuildError, UNSUPPORTED_CONTEXT_CHAIN
from agent.context_manager.manager.assembler import ContextPackAssembler
from agent.context_manager.models import BuildContextRequest
from agent.context_manager.resolvers import (EdslProjectContextResolver, GlobalContextResolver,
    LogicAreaContextResolver, OOTBContextResolver, ResourceContextResolver,
    SiteKnowledgeContextResolver)


class ContextManager:
    def __init__(self, loaded_resource: Any, global_resolver: Any = None,
                 edsl_resolver: Any = None, logic_resolver: Any = None,
                 resource_resolver: Any = None, ootb_resolver: Any = None,
                 site_resolver: Any = None, assembler: Any = None, **aliases: Any) -> None:
        self.loaded_resource = loaded_resource
        global_resolver = global_resolver or aliases.pop("global_context_resolver", None)
        edsl_resolver = edsl_resolver or aliases.pop("edsl_project_resolver", None)
        logic_resolver = logic_resolver or aliases.pop("logic_area_resolver", None)
        resource_resolver = resource_resolver or aliases.pop("resource_context_resolver", None)
        ootb_resolver = ootb_resolver or aliases.pop("ootb_context_resolver", None)
        site_resolver = site_resolver or aliases.pop("site_knowledge_context_resolver", None)
        if aliases:
            raise TypeError(f"Unexpected ContextManager arguments: {', '.join(sorted(aliases))}")
        self.global_resolver = global_resolver or GlobalContextResolver()
        self.edsl_resolver = edsl_resolver or EdslProjectContextResolver()
        self.logic_resolver = logic_resolver or LogicAreaContextResolver()
        self.resource_resolver = resource_resolver or ResourceContextResolver()
        self.ootb_resolver = ootb_resolver or OOTBContextResolver()
        self.site_resolver = site_resolver or SiteKnowledgeContextResolver()
        self.assembler = assembler or ContextPackAssembler()

    def build_context(self, request: BuildContextRequest):
        if request.chain_type != "namingsql_selection":
            raise ContextBuildError(UNSUPPORTED_CONTEXT_CHAIN, request.chain_type)
        global_block = self.global_resolver.resolve(request)
        node_block = self.edsl_resolver.resolve(request, self.loaded_resource)
        logic_block = self.logic_resolver.resolve(request, self.loaded_resource, node_block)
        resource_block = self.resource_resolver.resolve(request, self.loaded_resource, node_block, logic_block)
        resolver_context = {"node": node_block, "logic": logic_block}
        ootb_block = self.ootb_resolver.resolve(request, resolver_context)
        site_block = self.site_resolver.resolve(request, resolver_context)
        return self.assembler.assemble(request, global_block, node_block, logic_block,
                                       resource_block, ootb_block, site_block)
