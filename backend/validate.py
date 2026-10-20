from __future__ import annotations

import re
from typing import Iterator, TypedDict
import sqlglot
from sqlglot import exp


class ValidationResult(TypedDict):
    ok: bool
    reason: str | None


ALLOWED_TABLES = {
    "cnu_courses",
    "course_prerequisite",
    "department",
    "enrollment",
    "required_subject",
    "student",
    "subject",
    "v_course_info",
}
BLOCKED_KEYWORDS = ["insert", "update", "delete", "drop", "alter", "truncate"]
ALLOWED_STUDENT_COLUMNS = {
    "admission_year",
    "completed_credits",
    "dept_code",
    "grade",
    "student_id",
}
ALLOWED_STUDENT_ID_PLACEHOLDERS = {
    ":student_id",
    "%(student_id)s",
    "{{student_id}}",
}
STUDENT_SCOPED_TABLES = {"student", "enrollment"}

UNPARSEABLE_REASON = "SQL을 해석할 수 없습니다."
ALIAS_COLUMN_LIST_REASON = "{table}에 열 별칭 목록을 지정할 수 없습니다."

# Every security decision below is taken on the sqlglot AST of the SQL exactly as it will run
# (never on a lowercased copy and never on a regex over the text), so comments and string
# literals can never satisfy a check. SQL that sqlglot cannot parse is rejected (fail closed).


def _parse_sql(sql: str) -> exp.Expression | None:
    try:
        statements = [statement for statement in sqlglot.parse(sql, read="postgres") if statement is not None]
    except Exception:
        return None
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        return None
    return statements[0]


def _ident(node) -> str:
    """Identifier as PostgreSQL resolves it: unquoted names fold to lower case, quoted ones do not."""
    if node is None:
        return ""
    if isinstance(node, exp.Identifier):
        return node.this if node.quoted else node.this.lower()
    return str(node).lower()


def _table_ref(table: exp.Table) -> str:
    """The name columns use to qualify this table instance: its alias, or its own name."""
    alias = table.args.get("alias")
    if alias is not None and alias.args.get("this") is not None:
        return _ident(alias.args["this"])
    return _ident(table.args.get("this"))


def _column_qualifier(column: exp.Column) -> str:
    return _ident(column.args.get("table"))


def _column_name(column: exp.Column) -> str:
    return _ident(column.args.get("this"))


def _scoped_instances(ast: exp.Expression, table_name: str | None = None) -> list[exp.Table]:
    names = {table_name} if table_name else STUDENT_SCOPED_TABLES
    return [table for table in ast.find_all(exp.Table) if table.name.lower() in names]


def _owning_select(table: exp.Table) -> tuple[exp.Select | None, exp.Join | None]:
    """The SELECT whose FROM/JOIN list holds `table` directly, and the JOIN node if it is joined.

    Any other position (parenthesised join trees, LATERAL, ...) has no owner, so the instance
    can never be proven scoped and is rejected.
    """
    parent = table.parent
    if isinstance(parent, exp.From) and isinstance(parent.parent, exp.Select):
        return parent.parent, None
    if isinstance(parent, exp.Join) and isinstance(parent.parent, exp.Select):
        return parent.parent, parent
    return None, None


def _sources(select: exp.Select) -> list[exp.Expression]:
    sources = []
    from_clause = select.args.get("from_") or select.args.get("from")
    if from_clause is not None and from_clause.this is not None:
        sources.append(from_clause.this)
    sources.extend(join.this for join in select.args.get("joins") or [])
    return sources


def _conjuncts(node: exp.Expression | None) -> Iterator[exp.Expression]:
    """Top-level AND terms of a predicate, looking through parentheses and AND only."""
    if node is None:
        return
    if isinstance(node, exp.And):
        yield from _conjuncts(node.left)
        yield from _conjuncts(node.right)
    elif isinstance(node, exp.Paren):
        yield from _conjuncts(node.this)
    else:
        yield node


_PLACEHOLDER_SQL = {
    sqlglot.parse_one(f"SELECT 1 WHERE x = {placeholder}", read="postgres").find(exp.EQ).expression.sql(
        dialect="postgres"
    )
    for placeholder in ALLOWED_STUDENT_ID_PLACEHOLDERS
}


def _is_allowed_rhs(node: exp.Expression, requested_student_id: str | None) -> bool:
    if isinstance(node, exp.Literal):
        return requested_student_id is not None and node.this == str(requested_student_id)
    if isinstance(node, (exp.Placeholder, exp.Struct)):
        return node.sql(dialect="postgres") in _PLACEHOLDER_SQL
    return False


def _is_student_id_of(node: exp.Expression, table: exp.Table, single_source: bool) -> bool:
    if not isinstance(node, exp.Column) or _column_name(node) != "student_id":
        return False
    qualifier = node.args.get("table")
    if qualifier is None:
        return single_source
    if _column_qualifier(node) != _table_ref(table):
        return False
    db = node.args.get("db")
    return db is None or _ident(db) == _ident(table.args.get("db"))


def _is_instance_scoped(table: exp.Table, requested_student_id: str | None) -> bool:
    """`<ref>.student_id = <allowed rhs>` must be a top-level AND term of the owning SELECT's
    WHERE or of the instance's own JOIN ... ON."""
    select, join = _owning_select(table)
    if select is None:
        return False
    single_source = len(_sources(select)) == 1
    where = select.args.get("where")
    predicates = [where.this if where is not None else None]
    if join is not None:
        predicates.append(join.args.get("on"))
    for predicate in predicates:
        for term in _conjuncts(predicate):
            if not isinstance(term, exp.EQ):
                continue
            if _is_student_id_of(term.left, table, single_source) and _is_allowed_rhs(term.right, requested_student_id):
                return True
            if _is_student_id_of(term.right, table, single_source) and _is_allowed_rhs(term.left, requested_student_id):
                return True
    return False


def _is_order_by_output_name(column: exp.Column) -> bool:
    """A bare ORDER BY name resolves to an output column first in PostgreSQL."""
    ordered = column.parent
    if not isinstance(ordered, exp.Ordered) or not isinstance(ordered.parent, exp.Order):
        return False
    owner = ordered.parent.parent
    return isinstance(owner, exp.Query) and _column_name(column) in {
        name.lower() for name in owner.named_selects
    }


def _student_column_violations(table: exp.Table) -> set[str]:
    """Column references that may read a non-allowed column of this student instance.

    Conservative rule for unqualified columns: inside the SELECT that owns a student instance
    (including its nested subqueries, which may resolve a name to the student row by
    correlation) every unqualified column is treated as a possible student column and must be
    in ALLOWED_STUDENT_COLUMNS; the only exemption is a bare ORDER BY name that matches an
    output column. Multi-table queries must therefore qualify any other column. A bare
    reference to the student alias itself is a whole-row read and is reported as `*`.
    """
    select, _ = _owning_select(table)
    if select is None:
        return set()
    ref = _table_ref(table)
    violations = set()
    for column in select.find_all(exp.Column):
        qualifier = _column_qualifier(column)
        if isinstance(column.this, exp.Star):
            if qualifier == ref:
                violations.add("*")
            continue
        name = _column_name(column)
        if qualifier:
            if qualifier == ref and name not in ALLOWED_STUDENT_COLUMNS:
                violations.add(name)
            continue
        if name == ref:
            violations.add("*")
        elif name not in ALLOWED_STUDENT_COLUMNS and not _is_order_by_output_name(column):
            violations.add(name)
    for projection in select.expressions:
        if isinstance(projection, exp.Star):
            violations.add("*")
    return violations


def _star_violations(ast: exp.Expression) -> set[str]:
    """In a query that reads student, `*` and `t.*` may only expand base tables other than
    student; expanding a derived table (whose columns are not tracked) is rejected."""
    violations = set()
    for select in ast.find_all(exp.Select):
        base_refs = set()
        only_base_tables = True
        for source in _sources(select):
            if isinstance(source, exp.Table) and source.name and source.name.lower() != "student":
                base_refs.add(_table_ref(source))
            else:
                only_base_tables = False
        for projection in select.expressions:
            if isinstance(projection, exp.Star) and not only_base_tables:
                violations.add("*")
    for column in ast.find_all(exp.Column):
        if not isinstance(column.this, exp.Star):
            continue
        owner = column.find_ancestor(exp.Select)
        refs = set()
        if owner is not None:
            refs = {
                _table_ref(source)
                for source in _sources(owner)
                if isinstance(source, exp.Table) and source.name and source.name.lower() != "student"
            }
        if _column_qualifier(column) not in refs:
            violations.add("*")
    return violations


def _projects_instance(table: exp.Table) -> bool:
    select, _ = _owning_select(table)
    if select is None:
        return True
    ref = _table_ref(table)
    single_source = len(_sources(select)) == 1
    for projection in select.expressions:
        if isinstance(projection, exp.Star):
            return True
        for column in projection.find_all(exp.Column):
            qualifier = _column_qualifier(column)
            if qualifier == ref or (not qualifier and (single_source or _column_name(column) == ref)):
                return True
    return False


def _unscoped_instances(ast: exp.Expression, requested_student_id: str | None) -> list[exp.Table]:
    return [table for table in _scoped_instances(ast) if not _is_instance_scoped(table, requested_student_id)]


def unscoped_student_tables(sql: str, requested_student_id: str | None) -> set[str] | None:
    """Names of student/enrollment tables with at least one instance not pinned to the requested
    student; None when the SQL cannot be parsed."""
    ast = _parse_sql(sql)
    if ast is None:
        return None
    return {table.name.lower() for table in _unscoped_instances(ast, requested_student_id)}


def extract_table_references(sql: str) -> set[str]:
    ast = _parse_sql(sql)
    if ast is None:
        return set()
    return {table.name.lower() for table in ast.find_all(exp.Table) if table.name}


def extract_table_aliases(sql: str, table_name: str) -> set[str]:
    aliases = {table_name}
    ast = _parse_sql(sql)
    if ast is None:
        return aliases
    for table in ast.find_all(exp.Table):
        if table.name.lower() == table_name and table.alias:
            aliases.add(table.alias.lower())
    return aliases


def has_scoped_student_filter(sql: str, table_aliases: set[str], requested_student_id: str | None) -> bool:
    """True when the SQL parses, contains a student/enrollment instance named or aliased by one of
    `table_aliases`, and every such instance is scoped to the requested student."""
    ast = _parse_sql(sql)
    if ast is None:
        return False
    wanted = {alias.lower() for alias in table_aliases}
    instances = [
        table for table in _scoped_instances(ast)
        if table.name.lower() in wanted or _table_ref(table).lower() in wanted
    ]
    return bool(instances) and all(_is_instance_scoped(table, requested_student_id) for table in instances)


def validate_generated_sql(
    sql: str,
    requested_student_id: str | None = None,
    query: str | None = None,
) -> ValidationResult:
    normalized = sql.strip().lower()
    sql_without_trailing_semicolon = normalized[:-1].rstrip() if normalized.endswith(";") else normalized

    if not re.match(r"^select\b", normalized):
        return {"ok": False, "reason": "SELECT 문만 허용됩니다."}

    if ";" in sql_without_trailing_semicolon:
        return {"ok": False, "reason": "여러 문장은 허용되지 않습니다."}

    for keyword in BLOCKED_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", sql_without_trailing_semicolon):
            return {"ok": False, "reason": f"금지 키워드 포함: {keyword}"}

    original = sql.strip()
    if original.endswith(";"):
        original = original[:-1].rstrip()
    ast = _parse_sql(original)
    if ast is None:
        return {"ok": False, "reason": UNPARSEABLE_REASON}

    table_references = {table.name.lower() for table in ast.find_all(exp.Table) if table.name}
    if not table_references:
        return {"ok": False, "reason": "FROM 또는 JOIN 절이 필요합니다."}

    disallowed_tables = table_references - ALLOWED_TABLES
    if disallowed_tables:
        return {
            "ok": False,
            "reason": f"허용되지 않은 테이블 참조: {', '.join(sorted(disallowed_tables))}",
        }

    for table in _scoped_instances(ast):
        alias = table.args.get("alias")
        if alias is not None and alias.args.get("columns"):
            return {"ok": False, "reason": ALIAS_COLUMN_LIST_REASON.format(table=table.name.lower())}

    student_instances = _scoped_instances(ast, "student")
    if student_instances:
        disallowed_student_columns = _star_violations(ast)
        for table in student_instances:
            disallowed_student_columns |= _student_column_violations(table)
        if disallowed_student_columns:
            return {
                "ok": False,
                "reason": f"student에서 허용되지 않은 컬럼 참조: {', '.join(sorted(disallowed_student_columns))}",
            }

    unscoped = _unscoped_instances(ast, requested_student_id)
    for table_name in ("student", "enrollment"):
        instances = [table for table in unscoped if table.name.lower() == table_name]
        if not instances:
            continue
        # A student may read their own allowed columns; anything else keeps student filter-only.
        if table_name == "student" and any(_projects_instance(table) for table in instances):
            return {"ok": False, "reason": "student 테이블은 필터 조건으로만 사용할 수 있습니다."}
        return {
            "ok": False,
            "reason": f"{table_name}를 사용할 때는 요청된 학생의 학번으로 범위를 고정해야 합니다.",
        }

    if "limit" not in sql_without_trailing_semicolon:
        return {"ok": False, "reason": "기본 LIMIT가 필요합니다."}

    return {"ok": True, "reason": None}

if __name__ == "__main__":
    sample_sql1 = "SELECT c.* FROM v_course_info AS c JOIN (SELECT DISTINCT v_course_info.subject_code, v_course_info.section FROM v_course_info WHERE dept_name = '컴퓨터융합학부' AND target_year = 3 AND category = '전공(핵심)' AND day_of_week = '목') AS matched_courses ON c.subject_code = matched_courses.subject_code AND c.section IS NOT DISTINCT FROM matched_courses.section ORDER BY c.subject_code LIMIT 200"
    print(validate_generated_sql(sample_sql1))
