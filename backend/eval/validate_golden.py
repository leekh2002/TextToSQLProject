"""Check the golden set: reference SQL runs, empty results are flagged, fields are well-formed.

Usage: python -m backend.eval.validate_golden
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from ..db import run_query
from .grading import expand_reference_sql
from .run_eval import GOLDEN_QUERIES_PATH, load_cases

MAX_ROWS = 500
KNOWN_STUDENT_ID = "202102671"


def _gold_values_ok(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and set(item) == {"column", "value"}
        and isinstance(item["column"], str)
        and isinstance(item["value"], str)
        for item in value
    )


def check_cases(cases: list[dict], run=run_query, expand=expand_reference_sql) -> tuple[list[str], list[str]]:
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
        if row_count > MAX_ROWS:
            warnings.append(f"{case_id}: 정답 결과가 {row_count}행 (> {MAX_ROWS})")

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
