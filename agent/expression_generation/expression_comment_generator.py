from __future__ import annotations

import json
from typing import Any, Protocol

from agent.context_pack import ContextPack, ContextPackPromptRenderer
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.llm_planner import _summarize_typed_context_json


class ExpressionCommentGenerator(Protocol):
    def generate_comments(
        self,
        *,
        expression: str,
        user_query: str,
        node_info: NodeDef,
        typed_context: TypedExpressionContext,
        context_pack: ContextPack | None = None,
    ) -> list[dict[str, Any]]: ...


class NoOpExpressionCommentGenerator:
    def generate_comments(self, **_: Any) -> list[dict[str, Any]]:
        return []


class LLMExpressionCommentGenerator:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    def generate_comments(
        self,
        *,
        expression: str,
        user_query: str,
        node_info: NodeDef,
        typed_context: TypedExpressionContext,
        context_pack: ContextPack | None = None,
    ) -> list[dict[str, Any]]:
        if not self.client.is_usable:
            return []
        try:
            response = generate_by_llm(
                prompt_template="expression_comment_generator",
                llm_name="base",
                lang="zh",
                client=self.client,
                expression=expression,
                user_requirement=user_query,
                node_info_json=json.dumps(node_info.model_dump(), ensure_ascii=False),
                typed_context_json=_summarize_typed_context_json(typed_context),
                context_pack_json=ContextPackPromptRenderer().render_json(context_pack) if context_pack else "{}",
            )
        except Exception:
            return []
        comments = response.get("comments")
        return comments if isinstance(comments, list) else []
