from agent.context_manager.models import ContextAsset

from .embedding_client import EmbeddingClientProtocol
from .lexical import LexicalRetriever
from .semantic import SemanticRetriever


class HybridRetriever:
    def __init__(self, embedding_client: EmbeddingClientProtocol) -> None:
        self.semantic = SemanticRetriever(embedding_client)
        self.lexical = LexicalRetriever()

    def retrieve(
        self,
        query: str,
        assets: list[ContextAsset],
        semantic_limit: int = 10,
    ) -> list[ContextAsset]:
        if not assets:
            return []
        semantic_results = self.semantic.retrieve(query, assets, semantic_limit)
        lexical_results = self.lexical.retrieve(query, assets)
        results = []
        seen = set()
        for asset in [*semantic_results, *lexical_results]:
            if asset.asset_id in seen:
                continue
            results.append(asset)
            seen.add(asset.asset_id)
        return results
