"""Check the golden set: reference SQL runs, empty results are flagged, fields are well-formed,
and gold_values agree with the database for LIKE '%kw%' filters.

Usage: python -m backend.eval.validate_golden
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from ..db import run_query
from .grading import expand_reference_sql, row_cap
from .run_eval import GOLDEN_QUERIES_PATH, load_cases

# expand_schedule_filtered_course_rows caps the expanded query at LIMIT 200.
EXPANSION_CAP = 200
KNOWN_STUDENT_ID = "202102671"

# `[alias.]column LIKE '%kw%'` that is not preceded by NOT.
_LIKE_PATTERN = re.compile(
    r"(?<![\w.])(?:[a-z_][a-z0-9_]*\.)?([a-z_][a-z0-9_]*)\s+(not\s+)?i?like\s+'(%[^'%]+%)'",
    re.IGNORECASE,
)
_COLUMN_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def like_keywords(sql: str) -> dict[str, list[str]]:
    """Map column -> LIKE '%kw%' patterns filtering it in `sql` (NOT LIKE excluded)."""
    found: dict[str, list[str]] = {}
    for match in _LIKE_PATTERN.finditer(sql or ""):
        column, negated, pattern = match.group(1).lower(), match.group(2), match.group(3)
        if negated or column == "not":
            continue
        found.setdefault(column, [])
        if pattern not in found[column]:
            found[column].append(pattern)
    return found


def distinct_like_values(column: str, pattern: str) -> list[str]:
    """Distinct v_course_info values of `column` matching `pattern` (read-only lookup)."""
    if not _COLUMN_NAME.match(column):
        raise ValueError(f"잘못된 컬럼 이름: {column}")
    rows = run_query(
        f"SELECT DISTINCT {column} AS value FROM v_course_info WHERE {column} LIKE %s",
        (pattern,),
    )
    return sorted(str(row["value"]) for row in rows if row["value"] is not None)


def like_gold_problems(case: dict, distinct_like=distinct_like_values) -> list[str]:
    """gold_values for a LIKE '%kw%' column must be the single DB value kw matches, or be dropped."""
    keywords = like_keywords(case.get("reference_sql") or "")
    problems: list[str] = []
    for item in case.get("gold_values") or []:
        if not isinstance(item, dict):
            continue
        patterns = keywords.get(str(item.get("column", "")).lower())
        if not patterns:
            continue
        details = []
        unique_values = set()
        for pattern in patterns:
            values = distinct_like(item["column"], pattern)
            if len(values) == 1:
                unique_values.add(values[0])
            details.append(f"'{pattern}' -> DB 값 {len(values)}개")
        if item.get("value") in unique_values:
            continue
        if unique_values:
            fix = f"실제 DB 값 {sorted(unique_values)}로 고쳐야 함"
        else:
            fix = "키워드가 DB 값 하나로 특정되지 않으므로 빼야 함"
        problems.append(
            f"{case['id']}: gold_values {item['column']}={item.get('value')!r}가 LIKE 조건과 맞지 않음 "
            f"({', '.join(details)}); {fix}"
        )
    return problems


def _gold_values_ok(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and set(item) == {"column", "value"}
        and isinstance(item["column"], str)
        and isinstance(item["value"], str)
        for item in value
    )


def check_cases(
    cases: list[dict],
    run=run_query,
    expand=expand_reference_sql,
    distinct_like=distinct_like_values,
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []

    for case_id, count in Counter(case["id"] for case in cases).items():
        if count > 1:
            problems.append(f"id 중복: {case_id} ({count}회)")
    for query, count in Counter(case["query"] for case in cases).items():
        if count > 1:
            problems.append(f"질의 중복: {query} ({count}회)")

    for case in cases:
        case_id = case["id"]
        if "gold_values" in case and not _gold_values_ok(case["gold_values"]):
            problems.append(f"{case_id}: gold_values 형식 오류")
        if case.get("student_id") and not case.get("expects_error") and case["student_id"] != KNOWN_STUDENT_ID:
            problems.append(f"{case_id}: 학생 케이스는 학번 {KNOWN_STUDENT_ID}만 사용")
        if case.get("reference_sql") and _gold_values_ok(case.get("gold_values", [])):
            try:
                problems.extend(like_gold_problems(case, distinct_like))
            except Exception as exc:
                problems.append(f"{case_id}: LIKE 키워드의 DB 값 조회 실패: {exc}")
        if case.get("grading") != "execution":
            continue
        try:
            row_count = len(run(expand(case["reference_sql"])))
        except Exception as exc:
            problems.append(f"{case_id}: reference_sql 실행 실패: {exc}")
            continue
        if row_count == 0 and not case.get("empty_gold"):
            problems.append(f"{case_id}: 정답 결과가 0행인데 empty_gold가 아님")
        if row_count > 0 and case.get("empty_gold"):
            problems.append(f"{case_id}: empty_gold인데 정답 결과가 {row_count}행")
        cap = row_cap()
        if row_count > cap:
            warnings.append(
                f"{case_id}: 정답 결과가 {row_count}행 (> {cap}); 생성 결과는 LIMIT {cap}로 잘리므로 "
                f"ROW_CAP 규칙(정확히 {cap}행이고 모두 정답에 포함되면 통과)으로 채점됨"
            )
        if row_count == EXPANSION_CAP:
            warnings.append(f"{case_id}: 스케줄 확장 상한 {EXPANSION_CAP}행에 걸림 (정답 결과가 잘렸을 수 있음)")

    return problems, warnings


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cases = load_cases(GOLDEN_QUERIES_PATH)
    problems, warnings = check_cases(cases)

    counts = Counter(case["category"] for case in cases)
    print(f"케이스 {len(cases)}개")
    for category, count in sorted(counts.items()):
        print(f"  {category:<28} {count}")
    for warning in warnings:
        print(f"WARN  {warning}")
    for problem in problems:
        print(f"ERROR {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
