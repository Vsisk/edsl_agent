from __future__ import annotations

from .models import TreeReferenceCandidate, TreeReferenceResolveInput


class CandidateMerger:
    def merge(self, candidates: list[TreeReferenceCandidate], request: TreeReferenceResolveInput) -> list[TreeReferenceCandidate]:
        merged: dict[tuple[str, str], TreeReferenceCandidate] = {}
        for candidate in candidates:
            key = (candidate.node_id, candidate.json_path)
            if key not in merged:
                merged[key] = candidate.model_copy(deep=True)
            else:
                existing = merged[key]
                seen = {(item.source, item.reason) for item in existing.raw_evidence}
                existing.raw_evidence.extend(item for item in candidate.raw_evidence if (item.source, item.reason) not in seen)
        for candidate in merged.values():
            scores = {item.source: max(item.score, 0.0) for item in candidate.raw_evidence}
            candidate.confidence = min(1.0, 0.35 * scores.get("lexical", 0.0) + 0.30 * scores.get("structural", 0.0) + 0.20 * scores.get("exact", 0.0) + 0.15 * scores.get("embedding", 0.0))
            candidate.evidence = list(dict.fromkeys(item.reason for item in candidate.raw_evidence if item.reason))
            candidate.match_reason = "; ".join(candidate.evidence) or "local candidate match"
        return sorted(merged.values(), key=lambda item: (item.confidence, any(e.source == "exact" for e in item.raw_evidence)), reverse=True)[:max(0, request.max_candidates)]
