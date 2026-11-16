"""Deterministic SQL rewrites applied before execution (spec 3.4)."""
from __future__ import annotations

import sqlglot
from sqlglot import exp

STANDARD_COLUMNS = (
    "course_year", "subject_code", "section", "subject_name", "category", "credit_hours",
    "target_year", "professor", "capacity", "enrolled", "grading_method", "eval_type",
    "class_mode", "dept_name", "day_of_week", "start_time", "end_time", "classroom",
    "prereq_subject_codes", "prereq_subject_names",
)


def _parse(sql: str):
    try:
        return sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return None


def _course_source_alias(tree) -> str | None:
    if not isinstance(tree, exp.Select) or tree.args.get("joins"):
        return None
    source = tree.args.get("from_")
    table = source.this if source is not None else None
    if not isinstance(table, exp.Table) or table.name.lower() != "v_course_info":
        return None
    return table.alias_or_name


def is_course_row_query(sql: str) -> bool:
    tree = _parse(sql)
    if tree is None or _course_source_alias(tree) is None:
        return False
    if tree.args.get("group") or tree.args.get("having"):
        return False
    if tree.find(exp.AggFunc) or tree.find(exp.Window):
        return False
    distinct = tree.args.get("distinct")
    return not (distinct is not None and distinct.args.get("on"))


def _has_positional_order(tree) -> bool:
    order = tree.args.get("order")
    if order is None:
        return False
    return any(isinstance(ordered.this, exp.Literal) and ordered.this.is_int for ordered in order.expressions)


def _has_shadowing_alias(tree) -> bool:
    for expression in tree.expressions:
        if not isinstance(expression, exp.Alias) or expression.alias not in STANDARD_COLUMNS:
            continue
        inner = expression.this
        if not (isinstance(inner, exp.Column) and inner.name == expression.alias):
            return True
    return False


def normalize_projection(sql: str) -> str:
    if not is_course_row_query(sql):
        return sql
    tree = _parse(sql)
    if _has_positional_order(tree) or _has_shadowing_alias(tree):
        return sql
    alias = _course_source_alias(tree)
    extras = [
        expression for expression in tree.expressions
        if isinstance(expression, exp.Alias) and expression.alias not in STANDARD_COLUMNS
    ]
    tree.set("expressions", [exp.column(column, table=alias) for column in STANDARD_COLUMNS] + extras)
    tree.set("distinct", None)
    return tree.sql(dialect="postgres")


def ensure_limit(sql: str, cap: int) -> str:
    tree = _parse(sql)
    if tree is None or not isinstance(tree, (exp.Select, exp.SetOperation)):
        return sql
    if tree.args.get("limit") is not None:
        return sql
    return tree.limit(cap).sql(dialect="postgres")


def top_n_limit(sql: str) -> int | None:
    """The explicit integer LIMIT of an ordered query, or None (no ORDER BY, no LIMIT, unparseable)."""
    tree = _parse(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("order") is None:
        return None
    limit = tree.args.get("limit")
    value = limit.expression if limit is not None else None
    if isinstance(value, exp.Literal) and value.is_int:
        return int(value.name)
    return None


def _projects_course_keys(tree) -> bool:
    names = set()
    for expression in tree.expressions:
        if isinstance(expression, exp.Star):
            return True
        names.add(expression.alias_or_name)
    return {"subject_code", "section"} <= names


_DAY_ORDER = "CASE c.day_of_week WHEN '월' THEN 1 WHEN '화' THEN 2 WHEN '수' THEN 3 WHEN '목' THEN 4 WHEN '금' THEN 5 WHEN '토' THEN 6 ELSE 7 END"


def expand_top_n_course_rows(sql: str, cap: int) -> str | None:
    """Expand a top-N course-row query to all of its sections' meeting rows, keeping the top-N key set.

    process.expand_schedule_filtered_course_rows drops ORDER BY/LIMIT from the key subquery; this wraps the
    whole query instead. Rows are ordered by subject, section, weekday (Mon-Sat, same CASE as process), time.
    Returns None when the projection lacks subject_code/section (caller falls back to process' expansion).
    """
    tree = _parse(sql)
    if not isinstance(tree, exp.Select) or not _projects_course_keys(tree):
        return None
    return (
        "SELECT c.* FROM v_course_info AS c "
        f"JOIN (SELECT DISTINCT sub.subject_code, sub.section FROM ({sql}) AS sub) AS matched "
        "ON c.subject_code = matched.subject_code AND c.section IS NOT DISTINCT FROM matched.section "
        f"ORDER BY c.subject_code, c.section, {_DAY_ORDER}, c.start_time LIMIT {int(cap)}"
    )
