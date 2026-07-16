from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from agent.operation_orchestration.action_adapter import OperationActionAdapter
from agent.operation_orchestration.models import (
    CreateNodeInput,
    DeleteNodeInput,
    FinishInput,
    GenerateExpressionInput,
    ModifyNodeInput,
    Operation,
    SearchNodesInput,
    ToolCallTrace,
)
from agent.operation_orchestration.node_index import (
    NodeLocateCandidate,
    build_node_index,
    is_valid_candidate,
)
from agent.operation_orchestration.registry import (
    OperationToolRegistry,
    OperationToolSpec,
)


_SEARCH_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


class OperationToolRuntime:
    """Execute registered mapping-content tools against an atomic tree workspace."""

    def __init__(
        self,
        target_tree: dict[str, Any],
        *,
        action_adapter: Any | None = None,
        site_id: str | None = None,
        project_id: str | None = None,
        registry: OperationToolRegistry | None = None,
    ) -> None:
        self._tree = deepcopy(target_tree)
        self._index = build_node_index(self._tree)
        self._action_adapter = action_adapter or OperationActionAdapter()
        self.site_id = site_id
        self.project_id = project_id
        self.version = 0
        self.finished = False
        self.operations: list[Operation] = []
        self.traces: list[ToolCallTrace] = []
        self._authorized_candidates: set[tuple[str, str, str, int]] = set()
        self.registry = registry or OperationToolRegistry()
        if registry is None:
            self._register_builtin_tools()

    @property
    def tree(self) -> dict[str, Any]:
        return deepcopy(self._tree)

    @property
    def index(self) -> dict[str, NodeLocateCandidate]:
        return dict(self._index)

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        before = self.version
        step = len(self.traces)
        try:
            output = self.registry.execute(tool_name, arguments, self)
            if not isinstance(output, dict):
                raise ValueError("operation tool output must be an object")
        except Exception as exc:
            self.traces.append(
                ToolCallTrace(
                    step=step,
                    tool_name=tool_name,
                    arguments=deepcopy(arguments),
                    success=False,
                    error_message=f"{type(exc).__name__}: tool execution failed",
                    tree_version_before=before,
                    tree_version_after=self.version,
                )
            )
            raise
        self.traces.append(
            ToolCallTrace(
                step=step,
                tool_name=tool_name,
                arguments=deepcopy(arguments),
                output=deepcopy(output),
                success=True,
                tree_version_before=before,
                tree_version_after=self.version,
            )
        )
        return output

    def _register_builtin_tools(self) -> None:
        registrations = [
            (
                OperationToolSpec(
                    name="search_nodes",
                    description="Search current mapping-content nodes for one operation intent.",
                    input_model=SearchNodesInput,
                ),
                self._search_nodes,
            ),
            (
                OperationToolSpec(
                    name="create_node",
                    description="Create one node under an authorized parent candidate.",
                    input_model=CreateNodeInput,
                    mutates_tree=True,
                ),
                self._create_node,
            ),
            (
                OperationToolSpec(
                    name="modify_node",
                    description="Modify one authorized existing node.",
                    input_model=ModifyNodeInput,
                    mutates_tree=True,
                ),
                self._modify_node,
            ),
            (
                OperationToolSpec(
                    name="generate_expression",
                    description="Generate and write an expression for one authorized leaf.",
                    input_model=GenerateExpressionInput,
                    mutates_tree=True,
                ),
                self._generate_expression,
            ),
            (
                OperationToolSpec(
                    name="delete_node",
                    description="Delete one authorized node and return its parent.",
                    input_model=DeleteNodeInput,
                    mutates_tree=True,
                ),
                self._delete_node,
            ),
            (
                OperationToolSpec(
                    name="finish",
                    description="Finish after every requested operation has succeeded.",
                    input_model=FinishInput,
                ),
                self._finish,
            ),
        ]
        for spec, handler in registrations:
            self.registry.register(spec, handler)

    def _search_nodes(
        self, tool_input: SearchNodesInput, _: Any
    ) -> dict[str, Any]:
        ranked = [
            (self._relevance_score(candidate, tool_input.query), order, candidate)
            for order, candidate in enumerate(self._index.values())
            if is_valid_candidate(tool_input.intent_type, candidate)
        ]
        ranked.sort(key=lambda item: (-item[0], item[1]))
        candidates: list[dict[str, Any]] = []
        for score, _, candidate in ranked[: tool_input.limit]:
            item = candidate.model_dump(mode="json")
            item["candidate_version"] = self.version
            item["score"] = score
            candidates.append(item)
            self._authorized_candidates.add(
                (
                    tool_input.intent_type,
                    candidate.node_id,
                    candidate.jsonpath,
                    self.version,
                )
            )
        return {
            "version": self.version,
            "intent_type": tool_input.intent_type,
            "candidates": candidates,
        }

    @staticmethod
    def _relevance_score(candidate: NodeLocateCandidate, query: str) -> int:
        haystack = " ".join(
            str(value).casefold()
            for value in (
                candidate.node_id,
                candidate.xml_name,
                candidate.annotation,
                candidate.parent_xml_name,
                candidate.tree_node_type,
            )
            if value
        )
        normalized_query = query.strip().casefold()
        score = 100 if normalized_query and normalized_query in haystack else 0
        return score + sum(
            10 for token in _SEARCH_TOKEN.findall(normalized_query) if token in haystack
        )

    def _create_node(self, tool_input: CreateNodeInput, _: Any) -> dict[str, Any]:
        return self._mutate("create_node", tool_input)

    def _modify_node(self, tool_input: ModifyNodeInput, _: Any) -> dict[str, Any]:
        return self._mutate("modify_node", tool_input)

    def _generate_expression(
        self, tool_input: GenerateExpressionInput, _: Any
    ) -> dict[str, Any]:
        return self._mutate("generate_expression", tool_input)

    def _delete_node(self, tool_input: DeleteNodeInput, _: Any) -> dict[str, Any]:
        return self._mutate("delete_node", tool_input)

    def _mutate(
        self,
        intent_type: str,
        tool_input: CreateNodeInput
        | ModifyNodeInput
        | GenerateExpressionInput
        | DeleteNodeInput,
    ) -> dict[str, Any]:
        authorization = (
            intent_type,
            tool_input.target_node_id,
            tool_input.target_jsonpath,
            tool_input.candidate_version,
        )
        if (
            tool_input.candidate_version != self.version
            or authorization not in self._authorized_candidates
        ):
            raise ValueError(
                "target must be an authorized search candidate from the current tree version"
            )
        candidate = self._index.get(tool_input.target_node_id)
        if (
            candidate is None
            or candidate.jsonpath != tool_input.target_jsonpath
            or not is_valid_candidate(intent_type, candidate)
        ):
            raise ValueError(
                "target must be an authorized search candidate from the current tree version"
            )

        operation = Operation(
            op_id=f"tool_op_{len(self.operations)}",
            query=tool_input.query,
            intent_type=intent_type,
            target_node_id=candidate.node_id,
            target_jsonpath=candidate.jsonpath,
            status="located",
        )
        attempt_tree = deepcopy(self._tree)
        result = self._dispatch(intent_type, tool_input, attempt_tree)
        if not isinstance(result, dict):
            raise ValueError("adapter result must be an object")
        candidate_tree = result.get("target_tree")
        if not isinstance(candidate_tree, dict):
            raise ValueError("adapter result target_tree must be an object")
        candidate_tree = deepcopy(candidate_tree)
        candidate_index = build_node_index(candidate_tree)
        output_node_id = self._output_node_id(intent_type, candidate.node_id, result)
        if not isinstance(output_node_id, str) or not output_node_id.strip():
            raise ValueError("adapter result output node ID is blank or missing")
        output_candidate = candidate_index.get(output_node_id)
        if output_candidate is None:
            raise ValueError(
                f"adapter result output node ID is absent from resulting index: {output_node_id}"
            )

        self._tree = candidate_tree
        self._index = candidate_index
        self.version += 1
        self._authorized_candidates.clear()
        operation.output_node_id = output_node_id
        operation.status = "executed"
        self.operations.append(operation)
        output = {
            "version": self.version,
            "target_node_id": candidate.node_id,
            "output_node_id": output_node_id,
            "output_jsonpath": output_candidate.jsonpath,
        }
        if intent_type == "create_node":
            output["created_node_id"] = output_node_id
            output["created_jsonpath"] = output_candidate.jsonpath
        if intent_type == "delete_node":
            output["parent_node_id"] = output_node_id
        return output

    def _dispatch(
        self,
        intent_type: str,
        tool_input: CreateNodeInput
        | ModifyNodeInput
        | GenerateExpressionInput
        | DeleteNodeInput,
        attempt_tree: dict[str, Any],
    ) -> dict[str, Any]:
        if intent_type == "create_node":
            return self._action_adapter.create_node(
                tool_input.query, tool_input.target_jsonpath, attempt_tree
            )
        if intent_type == "modify_node":
            return self._action_adapter.modify_node(
                tool_input.query,
                tool_input.target_jsonpath,
                attempt_tree,
                site_id=self.site_id,
                project_id=self.project_id,
            )
        if intent_type == "generate_expression":
            return self._action_adapter.generate_expression(
                tool_input.query,
                tool_input.target_jsonpath,
                attempt_tree,
                site_id=self.site_id,
                project_id=self.project_id,
            )
        if intent_type == "delete_node":
            return self._action_adapter.delete_node(
                tool_input.target_jsonpath, attempt_tree
            )
        raise ValueError(f"unsupported operation intent: {intent_type}")

    @staticmethod
    def _output_node_id(
        intent_type: str, target_node_id: str, result: dict[str, Any]
    ) -> Any:
        if intent_type == "create_node":
            return result.get("created_node_id")
        if intent_type in {"modify_node", "generate_expression"}:
            return target_node_id
        if intent_type == "delete_node":
            return result.get("parent_node_id")
        return None

    def _finish(self, tool_input: FinishInput, _: Any) -> dict[str, Any]:
        self.finished = True
        return {"version": self.version, "summary": tool_input.summary}
