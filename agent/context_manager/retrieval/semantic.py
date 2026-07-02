import math

from agent.context_manager.errors import EMBEDDING_FAILED, ContextBuildError
from agent.context_manager.models import ContextAsset

from .embedding_client import EmbeddingClientProtocol


class SemanticRetriever:
    def __init__(self, embedding_client: EmbeddingClientProtocol) -> None:
        self.embedding_client = embedding_client

    def retrieve(self, query: str, assets: list[ContextAsset], limit: int) -> list[ContextAsset]:
        if not assets or limit <= 0:
            return []
        try:
            vectors = self.embedding_client.embed_texts([query, *(asset.index_text for asset in assets)])
            self._validate(vectors, len(assets) + 1)
            query_vector = vectors[0]
            ranked = [
                (self._cosine(query_vector, vector), index, asset)
                for index, (asset, vector) in enumerate(zip(assets, vectors[1:]))
            ]
        except ContextBuildError:
            raise
        except Exception as exc:
            raise ContextBuildError(EMBEDDING_FAILED) from exc

        ranked.sort(key=lambda item: (-item[0], item[1]))
        results = []
        for similarity, _, asset in ranked[:limit]:
            copied = asset.model_copy(deep=True)
            copied.metadata["embedding_similarity"] = similarity
            results.append(copied)
        return results

    @staticmethod
    def _validate(vectors: list[list[float]], expected_count: int) -> None:
        if len(vectors) != expected_count or not vectors:
            raise ContextBuildError(EMBEDDING_FAILED)
        dimension = len(vectors[0])
        if dimension == 0 or any(len(vector) != dimension for vector in vectors):
            raise ContextBuildError(EMBEDDING_FAILED)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for vector in vectors
            for value in vector
        ):
            raise ContextBuildError(EMBEDDING_FAILED)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        left_scale = max(abs(value) for value in left)
        right_scale = max(abs(value) for value in right)
        if left_scale == 0 or right_scale == 0:
            return 0.0
        scaled_left = [value / left_scale for value in left]
        scaled_right = [value / right_scale for value in right]
        left_norm = math.sqrt(sum(value * value for value in scaled_left))
        right_norm = math.sqrt(sum(value * value for value in scaled_right))
        similarity = sum(a * b for a, b in zip(scaled_left, scaled_right)) / (left_norm * right_norm)
        if not math.isfinite(similarity):
            raise ContextBuildError(EMBEDDING_FAILED)
        return max(-1.0, min(1.0, similarity))
