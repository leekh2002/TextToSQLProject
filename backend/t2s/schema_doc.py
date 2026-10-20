"""M-Schema text for the prompt: human-written Korean column docs + values read from the DB."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

DOCS_PATH = Path(__file__).with_name("schema_docs.yaml")
FULL_VALUES_MAX = 20
EXAMPLE_COUNT = 3


def load_column_docs(path: Path = DOCS_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _values_text(table: str, column: str, fetch) -> str:
    count = fetch(f"SELECT COUNT(DISTINCT {column}) AS n FROM {table}")[0]["n"]
    if count <= FULL_VALUES_MAX:
        rows = fetch(f"SELECT DISTINCT {column} AS v FROM {table} WHERE {column} IS NOT NULL ORDER BY 1")
        return f", Values: {[_plain(r['v']) for r in rows]}"
    rows = fetch(
        f"SELECT {column} AS v FROM {table} WHERE {column} IS NOT NULL "
        f"GROUP BY {column} ORDER BY COUNT(*) DESC LIMIT {EXAMPLE_COUNT}"
    )
    return f", Examples: {[_plain(r['v']) for r in rows]}"


def _plain(value):
    return value if isinstance(value, (int, float, str)) else str(value)


def build_mschema(docs: dict, fetch) -> str:
    lines: list[str] = []
    for table in docs["tables"]:
        lines.append(f"# Table: {table['name']} ({table['description']})")
        lines.append("[")
        columns = table["columns"]
        for i, column in enumerate(columns):
            values = _values_text(table["name"], column["name"], fetch) if column.get("values") == "auto" else ""
            comma = "," if i < len(columns) - 1 else ""
            lines.append(f"({column['name']}: {column['type']}, {column['description']}{values}){comma}")
        lines.append("]")
    if docs.get("foreign_keys"):
        lines.append("【Foreign keys】")
        lines.extend(docs["foreign_keys"])
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_mschema() -> str:
    from ..db import run_query

    return build_mschema(load_column_docs(), run_query)
