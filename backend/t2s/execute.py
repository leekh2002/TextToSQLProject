"""Validate, rewrite and run one candidate SQL (spec 3 ⑤)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import psycopg2

from ..validate import is_safety_rejection, validate_generated_sql
from .generate import extract_sql
from .postprocess import ensure_limit, is_course_row_query, normalize_projection

STUDENT_PLACEHOLDER = "%(student_id)s"
SELECT_ONLY_REASON = "SELECT 문만 허용됩니다."
WITH_UNSUPPORTED_REASON = "WITH 문은 지원하지 않습니다."
_WITH_PREFIX = re.compile(r"^\s*with\b", re.IGNORECASE)


@dataclass
class CandidateOutcome:
    index: int
    raw: str | None
    sql: str | None = None
    executed_sql: str | None = None
    rows: list[dict] | None = None
    error: str | None = None
    rejected: bool = False


def bind_student(sql: str, student_id):
    if STUDENT_PLACEHOLDER not in sql:
        return sql, None
    escaped = sql.replace("%", "%%").replace("%%(student_id)s", STUDENT_PLACEHOLDER)
    return escaped, {"student_id": student_id}


def run_sql(sql: str, params, timeout_ms: int) -> list[dict]:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg2.connect(dsn, connect_timeout=5, options=f"-c statement_timeout={int(timeout_ms)}")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d[0] for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _default_expand(sql):
    from ..process import expand_schedule_filtered_course_rows

    return expand_schedule_filtered_course_rows(sql)


def _default_exclude(sql, student_id):
    from ..process import exclude_completed_courses_sql

    return exclude_completed_courses_sql(sql, student_id)


def run_candidate(index, raw, *, student_id, exclude_completed, settings,
                  run=run_sql, validate=validate_generated_sql, expand=None, exclude=None) -> CandidateOutcome:
    outcome = CandidateOutcome(index=index, raw=raw)
    sql = extract_sql(raw)
    if sql is None:
        outcome.error = "SQL 없음"
        return outcome
    if sql == "UNKNOWN":
        outcome.rejected = True
        return outcome

    is_with = bool(_WITH_PREFIX.match(sql))
    course_rows = is_course_row_query(sql)
    sql = ensure_limit(normalize_projection(sql), settings.row_cap)
    outcome.sql = sql
    verdict = validate(sql, requested_student_id=student_id)
    if not verdict["ok"]:
        if is_with and verdict["reason"] == SELECT_ONLY_REASON:
            # A CTE is a generation-format miss, not a refusal.
            outcome.error = WITH_UNSUPPORTED_REASON
        elif is_safety_rejection(verdict["reason"]):
            outcome.rejected = True
        else:
            outcome.error = verdict["reason"]
        return outcome

    executable = (expand or _default_expand)(sql) if course_rows else sql
    if exclude_completed and student_id:
        executable = (exclude or _default_exclude)(executable, student_id)
    outcome.executed_sql = executable
    bound_sql, params = bind_student(executable, student_id)
    try:
        outcome.rows = run(bound_sql, params, settings.statement_timeout_ms)
    except Exception as exc:
        outcome.error = str(exc)
    return outcome
