from typing import Any, Dict, List

from agent.resource_manager.loader.tag_utils import build_tags
from agent.resource_manager.models import BoRegistry, NamingSqlDefTerm, PropertyTerm


def load_bo_registry_from_json(payload: Dict[str, Any]) -> List[BoRegistry]:
    registry: List[BoRegistry] = []

    for bo_payload in _iter_bo_payloads(payload):
        property_list = _collect_property_list(bo_payload)
        naming_sql_list = _collect_naming_sql_list(bo_payload)
        registry.append(
            BoRegistry(
                resource_id=f"bo.{len(registry):04d}",
                bo_name=bo_payload.get("bo_name") or "",
                bo_desc=bo_payload.get("bo_desc") or "",
                property_list=property_list,
                naming_sql_list=naming_sql_list,
                tag=_build_bo_tags(bo_payload, property_list, naming_sql_list),
            )
        )

    return registry


def load_bo_registry_by_json(payload: Dict[str, Any]) -> Dict[str, BoRegistry]:
    return {bo_registry.bo_name: bo_registry for bo_registry in load_bo_registry_from_json(payload)}


def _iter_bo_payloads(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    bo_payloads: List[Dict[str, Any]] = []
    for key in ("sys_bo_list", "custom_bo_list"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                bo_payloads.append(item)
    return bo_payloads


def _collect_naming_sql_list(bo_payload: Dict[str, Any]) -> List[NamingSqlDefTerm]:
    naming_sql_list: List[NamingSqlDefTerm] = []

    for mapping in bo_payload.get("or_mapping_list") or []:
        if not isinstance(mapping, dict):
            continue
        for naming_sql in mapping.get("naming_sql_list") or []:
            if isinstance(naming_sql, dict):
                naming_sql_list.append(NamingSqlDefTerm(**naming_sql))

    for naming_sql in bo_payload.get("naming_sql_list") or []:
        if isinstance(naming_sql, dict):
            naming_sql_list.append(NamingSqlDefTerm(**naming_sql))

    return naming_sql_list


def _collect_property_list(bo_payload: Dict[str, Any]) -> List[PropertyTerm]:
    property_list: List[PropertyTerm] = []
    for property_payload in bo_payload.get("property_list") or []:
        if isinstance(property_payload, dict):
            property_list.append(PropertyTerm(**property_payload))
    return property_list


def _build_bo_tags(
    bo_payload: Dict[str, Any],
    property_list: List[PropertyTerm],
    naming_sql_list: List[NamingSqlDefTerm],
) -> List[str]:
    values: List[str | None] = [
        bo_payload.get("bo_name"),
        bo_payload.get("bo_desc"),
    ]

    for property_payload in property_list:
        values.extend(
            [
                property_payload.field_name,
                property_payload.description,
                property_payload.data_type_name,
            ]
        )

    for naming_sql in naming_sql_list:
        values.extend(
            [
                naming_sql.sql_name,
                naming_sql.sql_description,
            ]
        )
        for param_payload in naming_sql.param_list:
            values.extend(
                [
                    param_payload.param_name,
                    param_payload.data_type_name,
                ]
            )

    return build_tags(*values)
