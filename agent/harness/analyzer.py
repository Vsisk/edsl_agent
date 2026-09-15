from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.harness.models import HarnessContext


@dataclass(frozen=True, slots=True)
class RequirementAnalysis:
    query: str
    workflows: tuple[str, ...]
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)


class RequirementAnalyzer:
    def analyze(
        self,
        *,
        query: str,
        context: HarnessContext,
    ) -> RequirementAnalysis:
        normalized = query.strip().lower()
        wants_node = any(token in normalized for token in ("新增", "生成字段", "添加字段", "create field", "add field"))
        wants_expression = any(
            token in normalized
            for token in ("取值逻辑", "表达式", "value logic", "expression", "生成对应的取值")
        )
        if wants_node and wants_expression:
            return RequirementAnalysis(
                query=query,
                workflows=("node_generation", "expression_generation"),
                inputs={
                    "node_generation": {"query": query},
                    "expression_generation": {"query": query},
                },
            )
        if wants_node:
            return RequirementAnalysis(
                query=query,
                workflows=("node_generation",),
                inputs={"node_generation": {"query": query}},
            )
        return RequirementAnalysis(
            query=query,
            workflows=("expression_generation",),
            inputs={"expression_generation": {"query": query}},
        )

