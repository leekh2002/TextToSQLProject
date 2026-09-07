from __future__ import annotations

import re

from ..validate import (
    extract_table_aliases,
    extract_table_references,
    has_scoped_student_filter,
)


def common_columns(rows_a: list[dict], rows_b: list[dict]) -> list[str]:
    if not rows_a or not rows_b:
        return []
    keys_a = set(rows_a[0].keys())
    keys_b = set(rows_b[0].keys())
    return sorted(keys_a & keys_b)


def project_rows(rows: list[dict], columns: list[str]) -> list[tuple]:
    return [tuple(row.get(column) for column in columns) for row in rows]


def compare_execution(
    reference_rows: list[dict],
    generated_rows: list[dict],
    order_sensitive: bool = False,
) -> tuple[bool, str | None]:
    if not reference_rows and not generated_rows:
        return True, None

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
