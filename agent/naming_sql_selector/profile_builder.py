import re

from agent.resource_manager.loader.registry_models import NamingSqlDefTerm
from agent.resource_manager.loader.tag_utils import build_tags

from .models import NamingSqlParamProfile, NamingSqlProfile


_WHERE_PATTERN = re.compile(r"\bWHERE\b(?P<predicate>.*)", re.IGNORECASE | re.DOTALL)
_PREDICATE_PATTERN = re.compile(
    r"(?<![\w])(?:[A-Za-z_][\w$]*\.)?(?P<field>[A-Za-z_][\w$]*)\s*"
    r"(?:=|!=|<>|<=|>=|<|>|LIKE\b|IN\b|BETWEEN\b|IS\b)",
    re.IGNORECASE,
)


class NamingSqlProfileBuilder:
    def build(self, site_id: str, bo_name: str, definition: NamingSqlDefTerm) -> NamingSqlProfile:
        fields = self._extract_filter_fields(definition.sql_command)
        params = [
            NamingSqlParamProfile(name=param.param_name, data_type=str(param.data_type or ""), is_list=param.is_list)
            for param in definition.param_list
        ]
        text_values = [
            definition.sql_name,
            definition.label_name or "",
            definition.sql_description or "",
            *fields,
            *(param.name for param in params),
        ]
        scope_tags = build_tags(*text_values)
        return NamingSqlProfile(
            site_id=site_id,
            bo_name=bo_name,
            naming_sql_id=definition.naming_sql_id,
            sql_name=definition.sql_name,
            label_name=definition.label_name or "",
            sql_description=definition.sql_description or "",
            params=params,
            filter_fields=fields,
            scope_tags=scope_tags,
            is_full_table=not fields,
            search_text=" ".join(tag.lower() for tag in scope_tags),
        )

    @staticmethod
    def _extract_filter_fields(sql_command: str | None) -> list[str]:
        if not sql_command:
            return []
        where_match = _WHERE_PATTERN.search(sql_command)
        if not where_match:
            return []
        fields: list[str] = []
        for match in _PREDICATE_PATTERN.finditer(where_match.group("predicate")):
            field = match.group("field")
            if field not in fields:
                fields.append(field)
        return fields
