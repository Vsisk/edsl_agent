from collections.abc import Iterable


def reciprocal_rank_fusion(rankings: list[list[str]], original_order: list[str]) -> list[str]:
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (60 + rank)
            best_rank[item_id] = min(best_rank.get(item_id, rank), rank)
    positions = {item_id: index for index, item_id in enumerate(original_order)}
    return sorted(scores, key=lambda item_id: (-scores[item_id], best_rank[item_id], positions[item_id]))
