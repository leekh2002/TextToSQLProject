from __future__ import annotations

import os
import re
from collections import Counter

from ..validate import (
    extract_table_aliases,
    extract_table_references,
    has_scoped_student_filter,
    unscoped_student_tables,
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


def row_cap() -> int:
    """Row limit the pipeline applies to generated SQL (read at call time)."""
    return int(os.getenv("T2S_ROW_CAP", "50"))


def _column_values(rows: list[dict], column: str) -> Counter:
    return Counter(row.get(column) for row in rows)


def match_columns(
    reference_rows: list[dict],
    generated_rows: list[dict],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pair each reference column with a generated column.

    A generated column with the same name wins; otherwise an unmatched generated column whose
    value multiset equals the reference column's is used (so `COUNT(*) AS count` can stand in for
    `AS course_count`). Returns (pairs, unmatched reference columns). Extra generated columns are ignored.
    """
    reference_columns = list(reference_rows[0].keys())
    generated_columns = list(generated_rows[0].keys())
    matched: dict[str, str] = {}
    used: set[str] = set()

    for column in reference_columns:
        if column in generated_columns:
            matched[column] = column
            used.add(column)

    capped = len(generated_rows) == row_cap()
    for column in reference_columns:
        if column in matched:
            continue
        reference_values = _column_values(reference_rows, column)
        if capped:
            reference_set = set(reference_values)
            candidates = [
                candidate for candidate in generated_columns
                if candidate not in used and set(_column_values(generated_rows, candidate)) <= reference_set
            ]
            if len(candidates) == 1:
                matched[column] = candidates[0]
                used.add(candidates[0])
            continue
        for candidate in generated_columns:
            if candidate in used:
                continue
            if _column_values(generated_rows, candidate) == reference_values:
                matched[column] = candidate
                used.add(candidate)
                break

    pairs = [(column, matched[column]) for column in reference_columns if column in matched]
    unmatched = [column for column in reference_columns if column not in matched]
    return pairs, unmatched


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

    pairs, unmatched = match_columns(reference_rows, generated_rows)
    if unmatched:
        return False, (
            f"생성 결과에서 대응하는 컬럼을 찾지 못한 정답 컬럼: {unmatched} "
            f"(generated={sorted(generated_rows[0].keys())})"
        )

    reference_projection = project_rows(reference_rows, [ref for ref, _ in pairs])
    generated_projection = project_rows(generated_rows, [gen for _, gen in pairs])

    if order_sensitive:
        ok = reference_projection == generated_projection
    else:
        ok = set(reference_projection) == set(generated_projection)

    if ok:
        return True, None

    # Truncated-but-correct: the pipeline caps generated SQL at row_cap() rows, so a result of
    # exactly that many rows, all of which belong to the reference (as a prefix when order
    # matters), is a pass.
    cap = row_cap()
    if len(generated_rows) == cap and len(set(generated_projection)) == len(generated_projection):
        if order_sensitive:
            if generated_projection == reference_projection[:cap]:
                return True, None
        elif set(generated_projection) <= set(reference_projection):
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
    """Row-level F1 over matched columns with set semantics (a simplified BIRD Soft-F1).

    Uses the same column matching and row deduplication as compare_execution.
    """
    if not reference_rows and not generated_rows:
        return 1.0
    if not reference_rows or not generated_rows:
        return 0.0
    pairs, _ = match_columns(reference_rows, generated_rows)
    if not pairs:
        return 0.0
    reference = set(project_rows(reference_rows, [ref for ref, _ in pairs]))
    generated = set(project_rows(generated_rows, [gen for _, gen in pairs]))
    true_positive = len(reference & generated)
    if true_positive == 0:
        return 0.0
    precision = true_positive / len(generated)
    recall = true_positive / len(reference)
    return round(2 * precision * recall / (precision + recall), 4)


def expand_reference_sql(sql: str) -> str:
    # Imported lazily: process.py pulls in the NER model and the vector cache.
    from ..process import expand_schedule_filtered_course_rows
    from ..t2s.postprocess import is_course_row_query

    # Same rule as the v2 pipeline: aggregates, GROUP BY and DISTINCT ON stay as written.
    if not is_course_row_query(sql):
        return sql
    return expand_schedule_filtered_course_rows(sql)


REFERENCE_FAILURE_PREFIX = "정답 SQL 실행 실패: "
UNSCOPED_STUDENT_REASON = "학생 범위 미지정"


def classify_failure(case: dict, result: dict, grade: dict) -> str:
    if grade.get("ok"):
        return "ok"
    if (grade.get("reason") or "").startswith(REFERENCE_FAILURE_PREFIX):
        return "infra_error"
    if case.get("expects_error") and not (isinstance(result, dict) and result.get("rejected") is True):
        return "reject_missed"
    if isinstance(result, dict) and result.get("error"):
        return "error"
    if case.get("grading") == "structural":
        return "structural_mismatch"
    if not (result or {}).get("data"):
        return "empty_result"
    return "result_mismatch"


def check_student_scope(sql: str, student_id: str | None) -> tuple[bool, str | None]:
    """Every student/enrollment table the SQL references must be pinned to the case's student."""
    unscoped = unscoped_student_tables(sql, student_id)
    if unscoped is None:
        # Fail closed: SQL that cannot be parsed cannot be shown to be scoped.
        return False, f"{UNSCOPED_STUDENT_REASON}: SQL을 해석할 수 없습니다"
    unscoped = sorted(unscoped)
    if unscoped:
        return False, f"{UNSCOPED_STUDENT_REASON}: {', '.join(unscoped)}"
    return True, None


def _execution_failure(case: dict, reason: str) -> dict:
    grade = {"ok": False, "reason": reason}
    if case.get("grading") == "execution":
        grade["soft_f1"] = 0.0
    return grade


def grade_case(case: dict, result: dict) -> dict:
    if case.get("expects_error"):
        if isinstance(result, dict) and result.get("rejected") is True:
            return {"ok": True, "reason": None}
        if isinstance(result, dict) and result.get("error"):
            return {"ok": False, "reason": f"거부가 예상되었지만 거부가 아닌 오류가 발생했습니다: {result['error']}"}
        return {"ok": False, "reason": "오류가 예상되었지만 SQL이 정상 생성되었습니다."}

    if isinstance(result, dict) and result.get("error"):
        return _execution_failure(case, f"예상치 못한 오류: {result['error']}")

    sql = result.get("sql") or ""

    if case.get("student_id"):
        ok, reason = check_student_scope(sql, case["student_id"])
        if not ok:
            return _execution_failure(case, reason)

    if case["grading"] == "structural":
        return _to_grade_dict(
            check_structural(sql, case.get("structural_checks") or {}, case.get("student_id"))
        )

    if case["grading"] == "execution":
        try:
            reference_rows = run_query(expand_reference_sql(case["reference_sql"]))
        except Exception as exc:
            return {"ok": False, "reason": f"{REFERENCE_FAILURE_PREFIX}{exc}"}
        generated_rows = result.get("data", [])
        ok, reason = compare_execution(reference_rows, generated_rows, case.get("order_sensitive", False))
        return {"ok": ok, "reason": reason, "soft_f1": soft_f1(reference_rows, generated_rows)}

    raise ValueError(f"알 수 없는 grading 값: {case['grading']}")
