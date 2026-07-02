from agent.context_manager.models import ContextAsset

from .lexical import LexicalRetriever
from .semantic import SemanticRetriever


class HybridRetriever:
    def __init__(self, semantic: SemanticRetriever, lexical: LexicalRetriever) -> None:
        self.semantic = semantic
        self.lexical = lexical

    def retrieve(
        self,
        query: str,
        assets: list[ContextAsset],
        semantic_limit: int = 10,
    ) -> list[ContextAsset]:
        if not assets:
            return []
        semantic_results = self.semantic.retrieve(query, assets, semantic_limit)
        seen = {asset.asset_id for asset in semantic_results}
        return semantic_results + [
            asset for asset in self.lexical.retrieve(query, assets) if asset.asset_id not in seen
        ]
