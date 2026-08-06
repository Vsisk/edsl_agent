from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from agent.resource_manager.loader.registry_models import BoRegistry


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
            if str(getattr(field.data_type, "value", field.data_type)).lower() == "key"
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
    match = re.search(r"\bselect\b(.*?)\bfrom\b", sql, re.IGNORECASE | re.DOTALL)
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
