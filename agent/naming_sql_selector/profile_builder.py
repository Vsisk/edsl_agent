import re

from agent.resource_manager.loader.registry_models import NamingSqlDefTerm
from agent.resource_manager.loader.tag_utils import tokenize_text

from .models import NamingSqlParamProfile, NamingSqlProfile


_IDENTIFIER = r"[A-Za-z_][\w$]*"
_CLAUSE_KEYWORDS = (
    r"AND|OR|WHERE|GROUP|ORDER|HAVING|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|CROSS|ON|"
    r"LIMIT|OFFSET|UNION|SELECT|FROM|NOT"
)
_VALUE = (
    rf"(?::(?:{_IDENTIFIER})|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[-+]?\d+(?:\.\d+)?|NULL\b|"
    rf"(?!(?:{_CLAUSE_KEYWORDS})\b){_IDENTIFIER}(?:\.{_IDENTIFIER})?)"
)
_IN_OPERANDS = rf"{_VALUE}(?:\s*,\s*{_VALUE})*"
_PREDICATE_PATTERN = re.compile(
    rf"(?<![\w])(?:{_IDENTIFIER}\.)?(?P<field>{_IDENTIFIER})\s*(?:"
    rf"(?:=|!=|<>|<=|>=|<|>|LIKE\b)\s*{_VALUE}"
    rf"|IN\s*(?:\(\s*{_IN_OPERANDS}\s*\)|:{_IDENTIFIER})"
    rf"|BETWEEN\s+{_VALUE}\s+AND\s+{_VALUE}"
    rf"|IS\s+(?:NOT\s+)?NULL\b)",
    re.IGNORECASE,
)
_CLAUSE_PATTERN = re.compile(
    r"\b(?P<kind>JOIN|ON|WHERE|GROUP(?:\s+BY)?|HAVING|ORDER(?:\s+BY)?|LIMIT)\b",
    re.IGNORECASE,
)
_AGGREGATE_PATTERN = re.compile(
    rf"\b(?P<aggregate>COUNT|SUM|AVG|MIN|MAX)\s*\([^)]*\)\s*(?:=|!=|<>|<=|>=|<|>)\s*{_VALUE}",
    re.IGNORECASE,
)


class NamingSqlProfileBuilder:
    def build(self, site_id: str, bo_name: str, definition: NamingSqlDefTerm) -> NamingSqlProfile:
        fields = self._extract_filter_fields(definition.sql_command)
        params = [
            NamingSqlParamProfile(name=param.param_name, data_type=str(param.data_type_name or ""), is_list=param.is_list)
            for param in definition.param_list
        ]
        text_values = [
            definition.sql_name,
            definition.label_name or "",
            definition.sql_description or "",
            *fields,
            *(param.name for param in params),
        ]
        scope_tags = tokenize_text(" ".join(text_values))
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
        sanitized_sql = _sanitize_sql(sql_command)
        fields: list[str] = []
        for clause_kind, region in _predicate_regions(sanitized_sql):
            matches = [(match.start(), match.group("field").upper()) for match in _PREDICATE_PATTERN.finditer(region)]
            if clause_kind == "HAVING":
                matches.extend(
                    (match.start(), match.group("aggregate").upper())
                    for match in _AGGREGATE_PATTERN.finditer(region)
                )
            for _, field in sorted(matches):
                if field not in fields:
                    fields.append(field)
        return fields


def _predicate_regions(sql: str) -> list[tuple[str, str]]:
    clauses = [
        (match, re.sub(r"\s+", " ", match.group("kind").upper()))
        for match in _CLAUSE_PATTERN.finditer(sql)
    ]
    regions: list[tuple[int, str, str]] = []
    pending_join = False
    for index, (clause, kind) in enumerate(clauses):
        if kind == "JOIN":
            pending_join = True
            continue
        if kind == "ON" and pending_join:
            pending_join = False
            end = _next_clause_start(
                clauses,
                index,
                {"JOIN", "WHERE", "GROUP", "GROUP BY", "HAVING", "ORDER", "ORDER BY", "LIMIT"},
                len(sql),
            )
            regions.append((clause.start(), "ON", sql[clause.end():end]))
            continue
        if kind in {"WHERE", "HAVING"}:
            pending_join = False
            stop_kinds = {"GROUP", "GROUP BY", "HAVING", "ORDER", "ORDER BY", "LIMIT"}
            if kind == "HAVING":
                stop_kinds = {"ORDER", "ORDER BY", "LIMIT"}
            end = _next_clause_start(clauses, index, stop_kinds, len(sql))
            regions.append((clause.start(), kind, sql[clause.end():end]))
            continue
        if kind not in {"ON"}:
            pending_join = False
    return [(kind, region) for _, kind, region in sorted(regions)]


def _next_clause_start(
    clauses: list[tuple[re.Match[str], str]], index: int, stop_kinds: set[str], default: int
) -> int:
    for clause, kind in clauses[index + 1:]:
        if kind in stop_kinds:
            return clause.start()
    return default


def _sanitize_sql(sql: str) -> str:
    """Remove comments and mask quoted contents without exposing predicate-like text."""
    result: list[str] = []
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            if newline < 0:
                break
            result.append("\n")
            index = newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                break
            result.append(" ")
            index = end + 2
            continue
        quote = sql[index]
        if quote in {"'", '"'}:
            result.append(quote * 2)
            index += 1
            closed = False
            while index < len(sql):
                if sql[index] != quote:
                    index += 1
                    continue
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                index += 1
                closed = True
                break
            if not closed:
                return ""
            continue
        result.append(sql[index])
        index += 1
    return "".join(result)
