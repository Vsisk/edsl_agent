from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from agent.workflow.core import StageResult, WorkflowDefinition, WorkflowRunState


@dataclass(frozen=True, slots=True)
class TransitionRule:
    from_stage: str
    to_stage: str | None
    observation_codes: tuple[str, ...] = ()
    result_status: str | None = "failed"
    output_equals: dict[str, Any] = field(default_factory=dict)

    def matches(self, *, stage_name: str, result: StageResult) -> bool:
        if self.from_stage != stage_name:
            return False
        if self.result_status is not None and self.result_status != result.status:
            return False
        for key, expected in self.output_equals.items():
            if result.outputs.get(key) != expected:
                return False
        if self.observation_codes:
            if result.observation is None:
                return False
            return result.observation.code in self.observation_codes
        return True


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    next_stage: str | None
    reason: str
    rule: TransitionRule | None = None


@dataclass(frozen=True, slots=True)
class TransitionPolicy:
    rules: tuple[TransitionRule, ...] = ()

    def resolve(
        self,
        *,
        definition: WorkflowDefinition,
        stage_name: str,
        result: StageResult,
    ) -> TransitionDecision:
        for rule in self.rules:
            if rule.matches(stage_name=stage_name, result=result):
                return TransitionDecision(
                    next_stage=rule.to_stage,
                    reason=f"rule:{stage_name}:{result.observation.code if result.observation else result.status}",
                    rule=rule,
                )
        return TransitionDecision(
            next_stage=definition.default_transitions.get(stage_name),
            reason=f"default:{stage_name}",
        )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_total_transitions: int = 32
    max_retry_per_stage: int = 3
    max_same_failure_fingerprint: int = 1
    max_same_artifact_fingerprint: int = 2
    artifact_keys: tuple[str, ...] = (
        "resources",
        "selected_resources",
        "typed_context",
        "ast",
        "final_expression",
    )


@dataclass(frozen=True, slots=True)
class LoopGuardDecision:
    allowed: bool
    reason: str | None = None
    failure_fingerprint: str | None = None
    artifact_fingerprint: str | None = None


class LoopGuard:
    def __init__(self, retry_policy: RetryPolicy | None = None) -> None:
        self.retry_policy = retry_policy or RetryPolicy()

    def check(
        self,
        *,
        state: WorkflowRunState,
        current_stage: str,
        next_stage: str | None,
        result: StageResult,
    ) -> LoopGuardDecision:
        if next_stage is None:
            return LoopGuardDecision(allowed=True)
        if len(state.transition_trace) >= self.retry_policy.max_total_transitions:
            return LoopGuardDecision(allowed=False, reason="max_total_transitions")
        next_attempt = state.stage_attempts.get(next_stage, 0) + 1
        if next_attempt > self.retry_policy.max_retry_per_stage:
            return LoopGuardDecision(allowed=False, reason="max_retry_per_stage")

        failure_fingerprint = self.failure_fingerprint(
            stage=current_stage,
            result=result,
            state=state,
        )
        artifact_fingerprint = self.artifact_fingerprint(state)
        if result.observation is not None:
            failure_count = state.failure_fingerprints.get(failure_fingerprint, 0) + 1
            if failure_count > self.retry_policy.max_same_failure_fingerprint:
                return LoopGuardDecision(
                    allowed=False,
                    reason="same_failure_fingerprint",
                    failure_fingerprint=failure_fingerprint,
                    artifact_fingerprint=artifact_fingerprint,
                )
        if state.stage_attempts.get(next_stage, 0) > 0:
            artifact_count = state.artifact_fingerprints.get(artifact_fingerprint, 0) + 1
            if artifact_count > self.retry_policy.max_same_artifact_fingerprint:
                return LoopGuardDecision(
                    allowed=False,
                    reason="same_artifact_fingerprint",
                    failure_fingerprint=failure_fingerprint,
                    artifact_fingerprint=artifact_fingerprint,
                )
        return LoopGuardDecision(
            allowed=True,
            failure_fingerprint=failure_fingerprint,
            artifact_fingerprint=artifact_fingerprint,
        )

    def record(
        self,
        *,
        state: WorkflowRunState,
        current_stage: str,
        next_stage: str | None,
        result: StageResult,
        decision: TransitionDecision,
        guard_decision: LoopGuardDecision,
    ) -> None:
        if guard_decision.failure_fingerprint is not None and result.observation is not None:
            state.failure_fingerprints[guard_decision.failure_fingerprint] = (
                state.failure_fingerprints.get(guard_decision.failure_fingerprint, 0) + 1
            )
        if guard_decision.artifact_fingerprint is not None:
            state.artifact_fingerprints[guard_decision.artifact_fingerprint] = (
                state.artifact_fingerprints.get(guard_decision.artifact_fingerprint, 0) + 1
            )
        state.transition_trace.append(
            {
                "from_stage": current_stage,
                "to_stage": next_stage,
                "status": result.status,
                "observation_code": result.observation.code if result.observation else None,
                "reason": decision.reason,
                "allowed": guard_decision.allowed,
                "guard_reason": guard_decision.reason,
                "failure_fingerprint": guard_decision.failure_fingerprint,
                "artifact_fingerprint": guard_decision.artifact_fingerprint,
            }
        )

    def failure_fingerprint(
        self,
        *,
        stage: str,
        result: StageResult,
        state: WorkflowRunState,
    ) -> str:
        observation = result.observation
        payload = {
            "stage": stage,
            "code": observation.code if observation else result.status,
            "missing_information": observation.missing_information if observation else [],
            "selected_resource_ids": _selected_resource_ids(state),
            "key_input": _normalized_key_input(state),
        }
        return _stable_hash(payload)

    def artifact_fingerprint(self, state: WorkflowRunState) -> str:
        payload = {
            key: _fingerprintable(state.artifacts.get(key))
            for key in self.retry_policy.artifact_keys
            if key in state.artifacts
        }
        return _stable_hash(payload)


def _selected_resource_ids(state: WorkflowRunState) -> list[str]:
    resources = state.artifacts.get("resources") or state.artifacts.get("selected_resources")
    ids: list[str] = []
    if isinstance(resources, dict):
        for value in resources.values():
            ids.extend(_ids_from_value(value))
    else:
        ids.extend(_ids_from_value(resources))
    return sorted(set(ids))


def _ids_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int)):
        return [str(value)]
    if isinstance(value, dict):
        result = []
        for key in ("id", "resource_id", "name", "key"):
            if value.get(key) is not None:
                result.append(str(value[key]))
        for nested in value.values():
            result.extend(_ids_from_value(nested))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_ids_from_value(item))
        return result
    result = []
    for key in ("id", "resource_id", "name", "key"):
        if hasattr(value, key):
            result.append(str(getattr(value, key)))
    return result


def _normalized_key_input(state: WorkflowRunState) -> dict[str, Any]:
    request = state.workflow_input.get("request")
    query = state.workflow_input.get("query") or getattr(request, "query", None)
    goal = state.workflow_input.get("goal")
    return {
        "query": str(query or "").strip().lower(),
        "goal": _fingerprintable(goal),
    }


def _fingerprintable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _fingerprintable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple, set)):
        return [_fingerprintable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _fingerprintable(value.model_dump(mode="json"))
    result = {}
    for key in ("id", "resource_id", "name", "key", "expression", "code"):
        if hasattr(value, key):
            result[key] = _fingerprintable(getattr(value, key))
    return result or str(value)


def _stable_hash(value: Any) -> str:
    raw = json.dumps(_fingerprintable(value), sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
