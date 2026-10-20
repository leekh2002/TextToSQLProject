from __future__ import annotations

import re
from collections import Counter

from ..validate import (
    extract_table_aliases,
    extract_table_references,
    has_scoped_student_filter,
)

from ..db import run_query


def common_columns(rows_a: list[dict], rows_b: list[dict]) -> list[str]:
    if not rows_a or not rows_b:
        return []
    keys_a = set(rows_a[0].keys())
    keys_b = set(rows_b[0].keys())
    return sorted(keys_a & keys_b)


def project_rows(rows: list[dict], columns: list[str]) -> list[tuple]:
    return [tuple(row.get(column) for column in columns) for row in rows]


IDENTITY_COLUMNS = ("subject_code", "section")


def _missing_identity_columns(reference_rows: list[dict], generated_rows: list[dict]) -> list[str]:
    reference_keys = set(reference_rows[0].keys())
    generated_keys = set(generated_rows[0].keys())
    return [
        column for column in IDENTITY_COLUMNS
        if column in reference_keys and column not in generated_keys
    ]


def compare_execution(
    reference_rows: list[dict],
    generated_rows: list[dict],
    order_sensitive: bool = False,
) -> tuple[bool, str | None]:
    if not reference_rows and not generated_rows:
        return True, None

    if not reference_rows or not generated_rows:
        return False, (
            f"reference={len(reference_rows)}행 vs generated={len(generated_rows)}행 (한쪽이 0행)"
        )

    missing_identity = _missing_identity_columns(reference_rows, generated_rows)
    if missing_identity:
        return False, f"생성 결과에 식별 컬럼이 없습니다: {', '.join(missing_identity)}"

    columns = common_columns(reference_rows, generated_rows)
    if not columns:
        reference_cols = sorted(reference_rows[0].keys()) if reference_rows else []
        generated_cols = sorted(generated_rows[0].keys()) if generated_rows else []
        return False, (
            f"컬럼이 겹치지 않습니다: reference={reference_cols}, generated={generated_cols}"
        )

    reference_projection = project_rows(reference_rows, columns)
    generated_projection = project_rows(generated_rows, columns)

    if order_sensitive:
        ok = reference_projection == generated_projection
    else:
        ok = set(reference_projection) == set(generated_projection)

    if ok:
        return True, None

    reference_set = set(reference_projection)
    generated_set = set(generated_projection)
    missing = reference_set - generated_set
    extra = generated_set - reference_set
    reason_parts = [f"reference={len(reference_rows)}행 vs generated={len(generated_rows)}행"]
    if missing:
        reason_parts.append(f"누락된 행 {len(missing)}개(예: {next(iter(missing))})")
    if extra:
        reason_parts.append(f"추가된 행 {len(extra)}개(예: {next(iter(extra))})")
    return False, "; ".join(reason_parts)


def check_required_tables(sql: str, required_tables: list[str]) -> tuple[bool, str | None]:
    referenced = extract_table_references(sql)
    missing = [table for table in required_tables if table not in referenced]
    if missing:
        return False, f"필요한 테이블이 SQL에 없습니다: {', '.join(missing)}"
    return True, None


def check_required_columns(sql: str, required_columns: list[str]) -> tuple[bool, str | None]:
    lowered_sql = sql.lower()
    missing = []
    for qualified_column in required_columns:
        table, separator, column = qualified_column.partition(".")
        if not separator:
            table, column = None, table

        patterns = []
        if table:
            aliases = extract_table_aliases(sql, table)
            patterns.extend(rf"\b{re.escape(alias)}\.{re.escape(column)}\b" for alias in aliases)
        patterns.append(rf"\b{re.escape(column)}\b")

        if not any(re.search(pattern, lowered_sql) for pattern in patterns):
            missing.append(qualified_column)

    if missing:
        return False, f"필요한 컬럼 참조가 SQL에 없습니다: {', '.join(missing)}"
    return True, None


def check_student_scoped(sql: str, student_id: str | None) -> tuple[bool, str | None]:
    student_aliases = extract_table_aliases(sql, "student")
    if not has_scoped_student_filter(sql, student_aliases, student_id):
        return False, "student 테이블 조회가 요청된 학생 학번으로 스코프되지 않았습니다."
    return True, None


def check_structural(
    sql: str,
    structural_checks: dict,
    student_id: str | None,
) -> tuple[bool, str | None]:
    structural_checks = structural_checks or {}
    ok, reason = check_required_tables(sql, structural_checks.get("required_tables", []))
    if not ok:
        return ok, reason

    ok, reason = check_required_columns(sql, structural_checks.get("required_columns", []))
    if not ok:
        return ok, reason

    if structural_checks.get("student_scoped"):
        ok, reason = check_student_scoped(sql, student_id)
        if not ok:
            return ok, reason

    return True, None


def _to_grade_dict(outcome: tuple[bool, str | None]) -> dict:
    ok, reason = outcome
    return {"ok": ok, "reason": reason}


def soft_f1(reference_rows: list[dict], generated_rows: list[dict]) -> float:
    """Row-level F1 over the common columns (a simplified BIRD Soft-F1)."""
    if not reference_rows and not generated_rows:
        return 1.0
    if not reference_rows or not generated_rows:
        return 0.0
    columns = common_columns(reference_rows, generated_rows)
    if not columns:
        return 0.0
    reference = Counter(project_rows(reference_rows, columns))
    generated = Counter(project_rows(generated_rows, columns))
    true_positive = sum((reference & generated).values())
    if true_positive == 0:
        return 0.0
    precision = true_positive / sum(generated.values())
    recall = true_positive / sum(reference.values())
    return round(2 * precision * recall / (precision + recall), 4)


def expand_reference_sql(sql: str) -> str:
    # Imported lazily: process.py pulls in the NER model and the vector cache.
    from ..process import expand_schedule_filtered_course_rows

    return expand_schedule_filtered_course_rows(sql)


def classify_failure(case: dict, result: dict, grade: dict) -> str:
    if grade.get("ok"):
        return "ok"
    if case.get("expects_error"):
        return "reject_missed"
    if isinstance(result, dict) and result.get("error"):
        return "error"
    if case.get("grading") == "structural":
        return "structural_mismatch"
    if not (result or {}).get("data"):
        return "empty_result"
    return "result_mismatch"


def grade_case(case: dict, result: dict) -> dict:
    if case.get("expects_error"):
        if isinstance(result, dict) and result.get("error"):
            return {"ok": True, "reason": None}
        return {"ok": False, "reason": "오류가 예상되었지만 SQL이 정상 생성되었습니다."}

    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "reason": f"예상치 못한 오류: {result['error']}"}

    sql = result.get("sql", "")

    if case["grading"] == "structural":
        return _to_grade_dict(
            check_structural(sql, case.get("structural_checks") or {}, case.get("student_id"))
        )

    if case["grading"] == "execution":
        reference_rows = run_query(expand_reference_sql(case["reference_sql"]))
        generated_rows = result.get("data", [])
        ok, reason = compare_execution(reference_rows, generated_rows, case.get("order_sensitive", False))
        return {"ok": ok, "reason": reason, "soft_f1": soft_f1(reference_rows, generated_rows)}

    raise ValueError(f"알 수 없는 grading 값: {case['grading']}")
