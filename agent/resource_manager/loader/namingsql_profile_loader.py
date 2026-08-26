from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.resource_manager.loader.registry_models import BoRegistry, NamingSqlDefTerm


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NamingSqlParamUsage:
    param_name: str
    field_name: str
    is_list: bool


class NamingSqlProfile(BaseModel):
    """Facts needed to decide whether a NamingSQL fits a query."""

    model_config = ConfigDict(extra="forbid")

    bo_name: str
    namingsql_name: str
    where_conditions: list[str] = Field(default_factory=list)
    return_fields: list[str] = Field(default_factory=list)
    performance_optimized: bool = False


class NamingSqlProfileLoader:
    """Build compact selection profiles from the canonical BO registry."""

    def load(self, bo_registry: dict[str, BoRegistry]) -> list[NamingSqlProfile]:
        return [
            profile
            for bo in bo_registry.values()
            for profile in self.load_bo(bo)
        ]

    def load_bo(self, bo: BoRegistry) -> list[NamingSqlProfile]:
        key_fields = {
            field.field_name.upper()
            for field in bo.property_list
            if bool(getattr(field, "is_key", False))
            or str(getattr(field.data_type, "value", field.data_type)).lower() == "key"
        }
        profiles = []
        for definition in bo.naming_sql_list:
            command = definition.sql_command or ""
            if _is_full_scan_where_one_equals_one(command):
                continue
            conditions = _where_conditions(command)
            profiles.append(
                NamingSqlProfile(
                    bo_name=bo.bo_name,
                    namingsql_name=definition.sql_name,
                    where_conditions=conditions,
                    return_fields=_return_fields(command),
                    performance_optimized=_uses_key_equality(conditions, key_fields),
                )
            )
        return profiles


def _return_fields(sql: str) -> list[str]:
    match = re.search(
        r"\bselect\b(.*?)\bfrom\b",
        strip_optimizer_hints(sql),
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    fields = []
    for raw in match.group(1).split(","):
        value = raw.strip()
        if not value:
            continue
        alias = re.search(r"\bas\s+([A-Za-z_][\w$]*)\s*$", value, re.IGNORECASE)
        field = alias.group(1) if alias else value.split(".")[-1].split()[-1]
        if field != "*":
            fields.append(field.strip("\"`[]").upper())
    return list(dict.fromkeys(fields))


def _where_conditions(sql: str) -> list[str]:
    match = re.search(
        r"\bwhere\b(.*?)(?:\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\blimit\b|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    conditions = [
        " ".join(item.strip().split())
        for item in re.split(r"\s+\b(?:and|or)\b\s+", match.group(1), flags=re.IGNORECASE)
    ]
    return [item for item in conditions if item and not re.fullmatch(r"1\s*=\s*1", item)]


def _is_full_scan_where_one_equals_one(sql: str) -> bool:
    match = re.search(
        r"\bwhere\b(.*?)(?:\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\blimit\b|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return False
    condition_text = " ".join(match.group(1).strip().split())
    return bool(re.fullmatch(r"1\s*=\s*1", condition_text))


def _uses_key_equality(conditions: list[str], key_fields: set[str]) -> bool:
    for condition in conditions:
        match = re.search(r"(?:^|\.)\b([A-Za-z_][\w$]*)\b\s*=", condition)
        if match and match.group(1).upper() in key_fields:
            return True
    return False


def strip_optimizer_hints(sql: str) -> str:
    return re.sub(r"/\*\+.*?\*/", " ", str(sql or ""), flags=re.DOTALL)


def parse_param_usages(sql: str) -> dict[str, NamingSqlParamUsage]:
    text = strip_optimizer_hints(sql)
    usages: dict[str, NamingSqlParamUsage] = {}
    conflicts: set[str] = set()

    for match in re.finditer(
        rf"(?P<field>{_FIELD})\s*\$\{{\s*(?P<op>in|not_in)\s*,\s*:(?P<param>{_IDENT})\s*\}}",
        text,
        flags=re.IGNORECASE,
    ):
        _add_usage(
            usages,
            conflicts,
            NamingSqlParamUsage(
                param_name=match.group("param"),
                field_name=_last_identifier(match.group("field")),
                is_list=True,
            ),
        )

    for match in re.finditer(
        rf"(?P<field>{_FIELD})\s*(?P<op><>|>=|<=|=|>|<)\s*:(?P<param>{_IDENT})",
        text,
        flags=re.IGNORECASE,
    ):
        if _function_like_prefix(text, match.start("field")):
            continue
        _add_usage(
            usages,
            conflicts,
            NamingSqlParamUsage(
                param_name=match.group("param"),
                field_name=_last_identifier(match.group("field")),
                is_list=False,
            ),
        )

    for key in conflicts:
        usages.pop(key, None)
    return usages


def enrich_naming_sql_definition(
    definition: NamingSqlDefTerm,
    bo: BoRegistry,
) -> NamingSqlDefTerm:
    usages = parse_param_usages(definition.sql_command or "")
    if not usages:
        return definition

    fields = {
        _normalize_name(field.field_name): field
        for field in bo.property_list
    }
    changed = False
    enriched_params = []
    for param in definition.param_list:
        usage = usages.get(_normalize_name(param.param_name))
        if usage is None:
            enriched_params.append(param)
            continue

        updates: dict[str, Any] = {"is_list": usage.is_list}
        field = fields.get(_normalize_name(usage.field_name))
        if field is not None:
            updates["linked_field_name"] = field.field_name
            data_type = field.data_type.value if hasattr(field.data_type, "value") else str(field.data_type)
            updates["data_type"] = data_type
            updates["data_type_name"] = field.data_type_name

        if param.is_list != usage.is_list:
            logger.warning(
                "NamingSQL param cardinality metadata conflicts with SQL usage: sql=%s param_name=%s metadata_is_list=%s sql_is_list=%s sql_field=%s",
                definition.sql_name,
                param.param_name,
                param.is_list,
                usage.is_list,
                usage.field_name,
            )
        logger.debug(
            "NamingSQL param enriched: sql=%s param_name=%s sql_field=%s is_list=%s linked_field_name=%s",
            definition.sql_name,
            param.param_name,
            usage.field_name,
            usage.is_list,
            updates.get("linked_field_name"),
        )
        enriched_params.append(param.model_copy(update=updates))
        changed = True

    if not changed:
        return definition
    return definition.model_copy(update={"param_list": enriched_params})


def naming_sql_param_field_contexts(
    definition: NamingSqlDefTerm,
    bo: BoRegistry,
) -> dict[str, dict[str, str | None]]:
    usages = parse_param_usages(definition.sql_command or "")
    if not usages:
        return {}
    fields = {
        _normalize_name(field.field_name): field
        for field in bo.property_list
    }
    contexts: dict[str, dict[str, str | None]] = {}
    for param in definition.param_list:
        usage = usages.get(_normalize_name(param.param_name))
        if usage is None:
            continue
        field = fields.get(_normalize_name(usage.field_name))
        if field is None:
            continue
        contexts[param.param_name] = {
            "field_name": field.field_name,
            "description": field.description,
        }
    return contexts


_IDENT = r"[A-Za-z_][\w$]*"
_FIELD = rf"(?:{_IDENT}\.)?{_IDENT}"


def _add_usage(
    usages: dict[str, NamingSqlParamUsage],
    conflicts: set[str],
    usage: NamingSqlParamUsage,
) -> None:
    key = _normalize_name(usage.param_name)
    existing = usages.get(key)
    if existing is not None and (
        _normalize_name(existing.field_name) != _normalize_name(usage.field_name)
        or existing.is_list != usage.is_list
    ):
        conflicts.add(key)
        logger.warning(
            "Ambiguous NamingSQL param usage ignored: param_name=%s field_a=%s list_a=%s field_b=%s list_b=%s",
            usage.param_name,
            existing.field_name,
            existing.is_list,
            usage.field_name,
            usage.is_list,
        )
        return
    usages[key] = usage


def _function_like_prefix(text: str, field_start: int) -> bool:
    prefix = text[:field_start].rstrip()
    return bool(prefix.endswith("("))


def _last_identifier(value: str) -> str:
    return str(value or "").split(".")[-1]


def _normalize_name(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())
