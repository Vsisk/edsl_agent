import json
import re
from typing import Any

from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.llm.prompt_manager import prompt_manager
from agent.models import NodeDef
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    DomainRegistry,
    FilterTarget,
    NamingSqlDefTerm,
    PropertyTerm,
    SourceType,
)


RESOURCE_GROUPS = ("global_context", "local_context", "bo", "function")

FILTER_TARGET_EMPTY = "FILTER_TARGET_EMPTY"


class LLMResourceFilter:
    def __init__(
        self,
        client: LLMClient | None = None,
    ):
        self.client = client or LLMClient()

    @property
    def is_usable(self) -> bool:
        return self.client.is_usable

    def filter_resources(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        candidates: dict[str, list[Any]],
        limits: dict[str, int],
    ) -> dict[str, list[dict[str, str]]]:
        if not self.is_usable:
            return {}

        response = generate_by_llm(
            prompt_template="resource_filter",
            llm_name="base",
            lang="zh",
            client=self.client,
            user_requirement=user_query,
            node_info_json=_dump_json(_summarize_node(node_info)),
            limits_json=_dump_json(limits),
            candidates_json=_dump_json(_summarize_candidates(candidates)),
        )
        return _normalize_response(response)

    def plan_resource_search_commands(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        search_space: dict[str, list[str]],
        limits: dict[str, int],
    ) -> dict[str, list[dict[str, str]]]:
        if not self.is_usable:
            return {"commands": []}

        response = generate_by_llm(
            prompt_template="resource_search_tool_trigger",
            llm_name="base",
            lang="zh",
            client=self.client,
            user_requirement=user_query,
            node_info_json=_dump_json(_summarize_node(node_info)),
            limits_json=_dump_json(limits),
            search_space_json=_dump_json(search_space),
        )
        return _normalize_search_commands(response)


def _summarize_node(node_info: NodeDef) -> dict[str, Any]:
    return {
        "node_id": node_info.node_id,
        "node_path": node_info.node_path,
        "node_name": node_info.node_name,
        "description": node_info.description,
    }


def _summarize_candidates(candidates: dict[str, list[Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        group: [_summarize_resource(resource, group) for resource in candidates.get(group, [])]
        for group in RESOURCE_GROUPS
    }


def _summarize_resource(resource: Any, group: str) -> dict[str, Any]:
    base = {
        "resource_id": getattr(resource, "resource_id", ""),
        "tags": list(getattr(resource, "tag", []) or []),
    }
    if group == "bo":
        base.update(
            {
                "name": getattr(resource, "bo_name", ""),
                "description": getattr(resource, "bo_desc", ""),
                "properties": [
                    {
                        "field_name": item.field_name,
                        "description": item.description,
                        "data_type_name": item.data_type_name,
                    }
                    for item in getattr(resource, "property_list", []) or []
                ],
                "naming_sql": [
                    {
                        "sql_name": item.sql_name,
                        "sql_description": item.sql_description,
                        "params": [
                            {
                                "param_name": param.param_name,
                                "data_type_name": param.data_type_name,
                            }
                            for param in item.param_list
                        ],
                    }
                    for item in getattr(resource, "naming_sql_list", []) or []
                ],
            }
        )
    elif group == "function":
        return_type = getattr(resource, "return_type", None)
        base.update(
            {
                "name": getattr(resource, "func_name", ""),
                "description": getattr(resource, "func_desc", ""),
                "class": getattr(resource, "func_class", ""),
                "params": [
                    {
                        "param_name": item.param_name,
                        "data_type_name": item.data_type_name,
                    }
                    for item in getattr(resource, "param_list", []) or []
                ],
                "return_type": getattr(return_type, "data_type_name", None),
            }
        )
    else:
        return_type = getattr(resource, "return_type", None)
        base.update(
            {
                "name": getattr(resource, "context_name", ""),
                "annotation": getattr(resource, "annotation", ""),
                "property_type": getattr(resource, "property_type", ""),
                "return_type": getattr(return_type, "data_type_name", None) if return_type else None,
            }
        )
    return base


def _normalize_response(response: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    normalized: dict[str, list[dict[str, str]]] = {}
    for group in RESOURCE_GROUPS:
        items = response.get(group) or []
        if not isinstance(items, list):
            normalized[group] = []
            continue
        normalized_items: list[dict[str, str]] = []
        for item in items:
            normalized_item = _normalize_item(item)
            if normalized_item:
                normalized_items.append(normalized_item)
        normalized[group] = normalized_items
    return normalized


def _normalize_search_commands(response: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    commands = response.get("commands") or []
    if not isinstance(commands, list):
        return {"commands": []}

    normalized_commands: list[dict[str, str]] = []
    for command in commands:
        if not isinstance(command, dict):
            continue
        tool = str(command.get("tool") or "").strip()
        group = str(command.get("group") or "").strip()
        keyword = str(command.get("keyword") or "").strip()
        if tool != "resource_keyword_search" or group not in RESOURCE_GROUPS or not keyword:
            continue
        normalized_commands.append(
            {
                "tool": tool,
                "group": group,
                "keyword": keyword,
            }
        )
    return {"commands": normalized_commands}


def _normalize_item(item: Any) -> dict[str, str]:
    if isinstance(item, str):
        return {"resource_id": item, "reason": ""}
    if not isinstance(item, dict):
        return {}
    resource_id = str(item.get("resource_id") or "").strip()
    if not resource_id:
        return {}
    return {
        "resource_id": resource_id,
        "reason": str(item.get("reason") or ""),
    }


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class ResourceFilterTargetGenerator:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()
        self.selection_trace: list[dict[str, Any]] = []

    @property
    def is_usable(self) -> bool:
        return self.client.is_usable

    def generate(
        self,
        *,
        query: str,
        domain_registry: DomainRegistry,
        resource_count_summary: dict[str, int] | None = None,
        retry_feedback: dict[str, Any] | None = None,
    ) -> list[FilterTarget]:
        self.selection_trace = []
        if not self.is_usable:
            self.selection_trace.append({"reason": FILTER_TARGET_EMPTY, "detail": "llm_unusable"})
            return []

        try:
            prompt = prompt_manager.render(
                "resource_filter_target",
                lang="zh",
                query=query,
                ctx_domains=_dump_json(domain_registry.ctx_domains),
                bo_domains=_dump_json(domain_registry.bo_domains),
                func_domains=_dump_json(domain_registry.func_domains),
                namingsql_domains=_dump_json(domain_registry.namingsql_domains),
                resource_count_summary=_dump_json(resource_count_summary or {}),
                retry_feedback_json=_dump_json(retry_feedback or {}),
            )
            content = self.client.complete(
                prompt=prompt,
                model=self.client.settings.model_for("base"),
                llm_name="base",
            )
            payload = _parse_json_array(content)
        except Exception as exc:
            self.selection_trace.append({"reason": FILTER_TARGET_EMPTY, "detail": str(exc)})
            return []

        targets = self._validate_targets(payload, domain_registry)
        if not targets:
            self.selection_trace.append({"reason": FILTER_TARGET_EMPTY, "detail": "no_valid_targets"})
        return targets

    def _validate_targets(self, payload: list[Any], domain_registry: DomainRegistry) -> list[FilterTarget]:
        valid_targets: list[FilterTarget] = []
        for raw in payload:
            if not isinstance(raw, dict):
                self.selection_trace.append({"target": raw, "reason": "INVALID_TARGET_SHAPE"})
                continue
            try:
                source_type = SourceType(str(raw.get("source_type") or "").strip())
            except ValueError:
                self.selection_trace.append({"target": raw, "reason": "INVALID_SOURCE_TYPE"})
                continue

            domain = str(raw.get("domain") or "").strip()
            source_name = str(raw.get("source_name") or "").strip()
            allowed_domains = _domains_for_type(domain_registry, source_type)
            if not allowed_domains or domain not in allowed_domains:
                self.selection_trace.append({"target": raw, "reason": "INVALID_DOMAIN"})
                continue
            if not source_name:
                self.selection_trace.append({"target": raw, "reason": "EMPTY_SOURCE_NAME"})
                continue

            valid_targets.append(
                FilterTarget(
                    source_type=source_type,
                    domain=domain,
                    source_name=source_name,
                    confidence=_coerce_float(raw.get("confidence"), 1.0),
                    is_required=_coerce_bool(raw.get("is_required"), True),
                    reason=str(raw.get("reason")).strip() if raw.get("reason") is not None else None,
                )
            )
        return valid_targets


class BaseDomainFilter:
    def filter(self, targets: list[FilterTarget], registry: dict[str, Any], top_k: int) -> list[Any]:
        raise NotImplementedError

    def select_by_name(
        self,
        *,
        candidates: list[Any],
        source_name: str,
        top_k: int,
        required: bool = True,
    ) -> list[Any]:
        if not candidates or not source_name:
            return []

        exact = [candidate for candidate in candidates if _candidate_name(candidate) == source_name]
        if exact:
            return exact

        normalized_name = _normalize_name(source_name)
        normalized_exact = [
            candidate for candidate in candidates if _normalize_name(_candidate_name(candidate)) == normalized_name
        ]
        if normalized_exact:
            return normalized_exact

        scored: list[tuple[float, int, Any]] = []
        for index, candidate in enumerate(candidates):
            score = _semantic_name_score(source_name, candidate)
            if score > 0:
                scored.append((score, index, candidate))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [candidate for _, _, candidate in scored[: max(top_k, 0)]]


class ContextFilter(BaseDomainFilter):
    def filter(self, targets: list[FilterTarget], registry: dict[str, Any], top_k: int) -> list[Any]:
        selected: list[Any] = []
        for target in targets:
            if target.source_type != SourceType.CONTEXT:
                continue
            candidates = _context_candidates_for_domain(registry, target.domain)
            selected.extend(
                self.select_by_name(
                    candidates=candidates,
                    source_name=target.source_name,
                    top_k=top_k,
                    required=target.is_required,
                )
            )
        return _dedupe_by_key(selected, lambda item: getattr(item, "context_name", ""))


class BOFilter(BaseDomainFilter):
    def filter(self, targets: list[FilterTarget], registry: dict[str, Any], top_k: int) -> list[BoRegistry]:
        by_bo: dict[str, BoRegistry] = {}
        for target in targets:
            if target.source_type != SourceType.BO:
                continue
            bo = registry.get(target.domain)
            if bo is None:
                continue
            matched = self.select_by_name(
                candidates=list(getattr(bo, "property_list", []) or []),
                source_name=target.source_name,
                top_k=top_k,
                required=target.is_required,
            )
            if not matched:
                continue
            _merge_bo(by_bo, _clone_bo(bo, property_list=matched, naming_sql_list=[]))
        return list(by_bo.values())


class FunctionFilter(BaseDomainFilter):
    def filter(self, targets: list[FilterTarget], registry: dict[str, Any], top_k: int) -> list[Any]:
        selected: list[Any] = []
        for target in targets:
            if target.source_type != SourceType.FUNCTION:
                continue
            candidates = [
                function for function in registry.values() if getattr(function, "func_class", "") == target.domain
            ]
            selected.extend(
                self.select_by_name(
                    candidates=candidates,
                    source_name=target.source_name,
                    top_k=top_k,
                    required=target.is_required,
                )
            )
        return _dedupe_by_key(selected, lambda item: f"{getattr(item, 'func_class', '')}.{getattr(item, 'func_name', '')}")


class NamingSQLFilter(BaseDomainFilter):
    def filter(self, targets: list[FilterTarget], registry: dict[str, Any], top_k: int) -> list[BoRegistry]:
        by_bo: dict[str, BoRegistry] = {}
        for target in targets:
            if target.source_type != SourceType.NAMING_SQL:
                continue
            bo = registry.get(target.domain)
            if bo is None:
                continue
            matched = self.select_by_name(
                candidates=list(getattr(bo, "naming_sql_list", []) or []),
                source_name=target.source_name,
                top_k=top_k,
                required=target.is_required,
            )
            if not matched:
                continue
            _merge_bo(by_bo, _clone_bo(bo, property_list=[], naming_sql_list=matched))
        return list(by_bo.values())


def _parse_json_array(content: str) -> list[Any]:
    text = str(content or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, list):
        raise ValueError("LLM response must be a JSON array")
    return payload


def _domains_for_type(domain_registry: DomainRegistry, source_type: SourceType) -> list[str]:
    if source_type == SourceType.CONTEXT:
        return domain_registry.ctx_domains
    if source_type == SourceType.BO:
        return domain_registry.bo_domains
    if source_type == SourceType.FUNCTION:
        return domain_registry.func_domains
    if source_type == SourceType.NAMING_SQL:
        return domain_registry.namingsql_domains
    return []


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return bool(value)


def _context_candidates_for_domain(registry: dict[str, Any], domain: str) -> list[Any]:
    prefix = f"$ctx$.{domain}."
    return [context for name, context in registry.items() if str(name).startswith(prefix)]


def _candidate_name(candidate: Any) -> str:
    for attr in ("context_name", "field_name", "func_name", "sql_name", "bo_name"):
        value = getattr(candidate, attr, None)
        if value:
            text = str(value)
            if attr == "context_name":
                return text.split(".")[-1]
            return text
    return ""


def _candidate_description(candidate: Any) -> str:
    parts = [
        getattr(candidate, "description", ""),
        getattr(candidate, "annotation", ""),
        getattr(candidate, "func_desc", ""),
        getattr(candidate, "sql_description", ""),
    ]
    return " ".join(str(part) for part in parts if part)


def _normalize_name(value: str) -> str:
    split_camel = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return "".join(ch.lower() for ch in split_camel.replace("_", " ") if ch.isalnum())


def _semantic_name_score(source_name: str, candidate: Any) -> float:
    source = _normalize_name(source_name)
    name = _normalize_name(_candidate_name(candidate))
    description = _normalize_name(_candidate_description(candidate))
    if not source or not name:
        return 0.0
    if source in name or name in source:
        return 0.8
    if source in description:
        return 0.5
    source_parts = set(re.findall(r"[A-Za-z0-9]+", source_name.lower()))
    candidate_parts = set(re.findall(r"[A-Za-z0-9]+", _candidate_name(candidate).lower()))
    if source_parts and candidate_parts:
        overlap = len(source_parts & candidate_parts) / len(source_parts | candidate_parts)
        if overlap:
            return overlap
    return 0.0


def _dedupe_by_key(items: list[Any], key_fn) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        key = str(key_fn(item))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _clone_bo(
    bo: BoRegistry,
    *,
    property_list: list[PropertyTerm],
    naming_sql_list: list[NamingSqlDefTerm],
) -> BoRegistry:
    return bo.model_copy(
        update={
            "property_list": list(property_list),
            "naming_sql_list": list(naming_sql_list),
        },
        deep=True,
    )


def _merge_bo(by_bo: dict[str, BoRegistry], bo: BoRegistry) -> None:
    existing = by_bo.get(bo.bo_name)
    if existing is None:
        by_bo[bo.bo_name] = bo
        return

    properties = _dedupe_by_key(
        [*existing.property_list, *bo.property_list],
        lambda item: getattr(item, "field_name", ""),
    )
    naming_sql = _dedupe_by_key(
        [*existing.naming_sql_list, *bo.naming_sql_list],
        lambda item: getattr(item, "sql_name", ""),
    )
    by_bo[bo.bo_name] = existing.model_copy(
        update={"property_list": properties, "naming_sql_list": naming_sql},
        deep=True,
    )
