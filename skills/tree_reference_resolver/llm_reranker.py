from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .models import CandidateEvidence, ReferenceSearchSpec, TreeReferenceCandidate, TreeReferenceResolveInput


class LLMClientProtocol(Protocol):
    def complete_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]: ...


class LLMReranker:
    def __init__(self, client: LLMClientProtocol | None = None, top_k: int = 10):
        self.client = client
        self.top_k = top_k
        self.last_error: str | None = None

    def rerank(self, request: TreeReferenceResolveInput, spec: ReferenceSearchSpec, candidates: list[TreeReferenceCandidate]) -> list[TreeReferenceCandidate]:
        top = [candidate.model_copy(deep=True) for candidate in candidates[: self.top_k]]
        if not top:
            return []
        if self.client is None:
            top[0].raw_evidence.append(CandidateEvidence(source="fallback", score=top[0].confidence, reason="selected by highest local score because no LLM client was configured"))
            top[0].evidence.append(top[0].raw_evidence[-1].reason)
            top[0].match_reason = "; ".join(top[0].evidence)
            return top
        payload = [
            {"node_id": item.node_id, "json_path": item.json_path, "xml_path": item.xml_path,
             "xml_name": item.xml_name, "tree_node_type": item.tree_node_type,
             "annotation": item.annotation, "local_confidence": item.confidence, "evidence": item.evidence}
            for item in top
        ]
        template = (Path(__file__).parent / "prompts" / "rerank_prompt.md").read_text(encoding="utf-8")
        prompt = template.replace("{{target_summary}}", spec.target_summary[:2000]).replace("{{candidates_json}}", json.dumps(payload, ensure_ascii=False))
        try:
            output = self.client.complete_json(prompt)
            node_id, json_path = output.get("selected_node_id"), output.get("selected_json_path")
            selected_index = next(index for index, item in enumerate(top) if item.node_id == node_id and item.json_path == json_path)
            selected = top.pop(selected_index)
            confidence = output.get("confidence")
            if isinstance(confidence, (int, float)):
                selected.confidence = max(0.0, min(1.0, float(confidence)))
            reason = str(output.get("match_reason") or "selected by LLM reranker")
            selected.raw_evidence.append(CandidateEvidence(source="llm", score=selected.confidence, reason=reason))
            selected.evidence.append(reason)
            selected.match_reason = reason
            return [selected, *top]
        except (KeyError, StopIteration, TypeError, ValueError, RuntimeError) as exc:
            self.last_error = type(exc).__name__
            top[0].raw_evidence.append(CandidateEvidence(source="fallback", score=top[0].confidence, reason="LLM rerank failed; selected by highest local score"))
            top[0].evidence.append(top[0].raw_evidence[-1].reason)
            top[0].match_reason = "; ".join(top[0].evidence)
            return top
