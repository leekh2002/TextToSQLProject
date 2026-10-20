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
