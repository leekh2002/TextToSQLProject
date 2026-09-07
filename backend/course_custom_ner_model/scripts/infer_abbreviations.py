from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

DEPARTMENT_PREFIX_RE = re.compile(r"^[가-힣]+대학\s+")
PARENTHETICAL_RE = re.compile(r"^(.+)\((.+)\)$")


def strip_department_prefix(value: str) -> str:
    return DEPARTMENT_PREFIX_RE.sub("", value)


def strip_known_suffix(value: str, suffixes: list[str]) -> str:
    for suffix in sorted(suffixes, key=len, reverse=True):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def mine_root_words(
    values: list[str], min_len: int = 2, max_len: int = 4, min_freq: int = 3
) -> list[str]:
    counts: Counter[str] = Counter()
    for value in values:
        length = len(value)
        for size in range(min_len, max_len + 1):
            for start in range(0, length - size + 1):
                counts[value[start : start + size]] += 1
    roots = [root for root, count in counts.items() if count >= min_freq]
    roots.sort(key=lambda root: (-len(root), -counts[root]))
    return roots


def segment_by_roots(value: str, roots: list[str]) -> list[str]:
    segments: list[str] = []
    index = 0
    while index < len(value):
        matched = None
        for root in roots:
            if value.startswith(root, index):
                matched = root
                break
        if matched:
            segments.append(matched)
            index += len(matched)
        else:
            segments.append(value[index])
            index += 1
    return segments


def abbreviate_by_initials(segments: list[str]) -> str:
    return "".join(segment[0] for segment in segments if segment)


def split_parenthetical(value: str) -> tuple[str, str] | None:
    match = PARENTHETICAL_RE.match(value)
    if not match:
        return None
    return match.group(1), match.group(2)


def _generic_candidates(value: str, roots: list[str], suffixes: list[str] | None) -> list[str]:
    candidates: list[str] = []

    trimmed = strip_department_prefix(value)
    without_suffix = strip_known_suffix(trimmed, suffixes) if suffixes else trimmed

    for source in (without_suffix, trimmed):
        segments = segment_by_roots(source, roots)
        candidate = abbreviate_by_initials(segments)
        if candidate and candidate != value and len(candidate) < len(value) and candidate not in candidates:
            candidates.append(candidate)

    return candidates


def generate_abbreviation_candidates(
    value: str,
    label: str,
    roots: list[str],
    suffixes: list[str] | None = None,
) -> list[str]:
    if label == "CATEGORY":
        parts = split_parenthetical(value)
        if parts:
            first, second = parts
            candidate = first[0] + second[0]
            return [candidate] if candidate != value else []
        return []

    return _generic_candidates(value, roots, suffixes)


def infer_abbreviations(
    values_by_label: dict[str, list[str]],
    suffixes_by_label: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for label, values in values_by_label.items():
        roots = mine_root_words(values)
        suffixes = suffixes_by_label.get(label, [])
        label_result: dict[str, list[str]] = {}
        for value in values:
            candidates = generate_abbreviation_candidates(value, label, roots, suffixes)
            if candidates:
                label_result[value] = candidates
        result[label] = label_result
    return result


def _build_postgres_dsn() -> str:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "")
    port = os.getenv("POSTGRES_PORT", "")
    database = os.getenv("POSTGRES_DB", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _fetch_distinct_values(dsn: str, table: str, column: str) -> list[str]:
    import psycopg2
    from psycopg2 import sql

    stmt = sql.SQL(
        "SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL AND TRIM(CAST({column} AS TEXT)) <> ''"
    ).format(column=sql.Identifier(column), table=sql.Identifier(table))
    with psycopg2.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(stmt)
            return [str(row[0]).strip() for row in cur.fetchall() if row[0]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer abbreviation candidates from live DB values")
    parser.add_argument(
        "--output",
        default="../data/abbreviation_candidates.json",
        help="Where to write the raw (unreviewed) candidates JSON",
    )
    args = parser.parse_args()

    dsn = _build_postgres_dsn()
    values_by_label = {
        "DEPARTMENT": _fetch_distinct_values(dsn, "v_course_info", "dept_name"),
        "CATEGORY": _fetch_distinct_values(dsn, "v_course_info", "category"),
        "COURSE_NAME": _fetch_distinct_values(dsn, "v_course_info", "subject_name"),
    }
    suffixes_by_label = {
        "DEPARTMENT": ["학과", "학부", "전공"],
        "CATEGORY": [],
        "COURSE_NAME": [],
    }

    result = infer_abbreviations(values_by_label, suffixes_by_label)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
