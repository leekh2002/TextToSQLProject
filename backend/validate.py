from __future__ import annotations

import re
from typing import TypedDict
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


def _parse_sql(sql: str) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return None


def extract_table_references(sql: str) -> set[str]:
    ast = _parse_sql(sql)
    if ast:
        return {table.name.lower() for table in ast.find_all(exp.Table) if table.name}
    
    # Fallback to regex if parsing fails
    clean_sql = re.sub(r"\bis\s+not\s+distinct\s+from\b", "=", sql, flags=re.IGNORECASE)
    matches = re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)\b", clean_sql)
    return set(matches)


def extract_table_aliases(sql: str, table_name: str) -> set[str]:
    aliases = {table_name}
    ast = _parse_sql(sql)
    if ast:
        for table in ast.find_all(exp.Table):
            if table.name.lower() == table_name and table.alias:
                aliases.add(table.alias.lower())
        return aliases

    # Fallback to regex
    matches = re.findall(
        rf"\b(?:from|join)\s+{re.escape(table_name)}(?:\s+as)?\s+([a-z_][a-z0-9_]*)\b",
        sql,
    )
    aliases.update(matches)
    return aliases


def _is_single_table_student_query(sql: str) -> bool:
    # In a query whose only table is student, unqualified columns (and a bare *) belong to student.
    return extract_table_references(sql) == {"student"}


def _projection_aliases(ast: exp.Expression) -> set[str]:
    return {
        projection.alias.lower()
        for select in ast.find_all(exp.Select)
        for projection in select.expressions
        if isinstance(projection, exp.Alias) and projection.alias
    }


def _is_student_column(column: exp.Column, student_aliases: set[str], unqualified_is_student: bool) -> bool:
    qualifier = column.table.lower()
    return qualifier in student_aliases or (unqualified_is_student and not qualifier)


_SELECT_ITEM_PATTERN = re.compile(
    r"^\s*(?:distinct\s+)?(\*|[a-z_][a-z0-9_]*)\s*(?:(?:as\s+)?[a-z_][a-z0-9_]*\s*)?$"
)


def _unqualified_select_columns(sql: str) -> set[str]:
    """Regex fallback: plain column names (or *) projected by a single-table student query."""
    select_match = re.search(r"\bselect\b(.*?)\bfrom\b", sql, flags=re.DOTALL)
    if not select_match:
        return set()
    columns = set()
    for item in select_match.group(1).split(","):
        match = _SELECT_ITEM_PATTERN.match(item)
        if match:
            columns.add(match.group(1))
    return columns


def find_disallowed_student_columns(sql: str, student_aliases: set[str]) -> set[str]:
    referenced_columns: set[str] = set()
    unqualified_is_student = _is_single_table_student_query(sql)
    ast = _parse_sql(sql)
    if ast:
        output_aliases = _projection_aliases(ast) if unqualified_is_student else set()
        for column in ast.find_all(exp.Column):
            if not _is_student_column(column, student_aliases, unqualified_is_student):
                continue
            if not column.table and column.name.lower() in output_aliases:
                continue
            referenced_columns.add(column.name.lower())
        if unqualified_is_student:
            for select in ast.find_all(exp.Select):
                if any(isinstance(projection, exp.Star) for projection in select.expressions):
                    referenced_columns.add("*")
        return referenced_columns - ALLOWED_STUDENT_COLUMNS

    # Fallback to regex
    for alias in student_aliases:
        pattern = rf"\b{re.escape(alias)}\.([a-z_][a-z0-9_]*)\b"
        referenced_columns.update(re.findall(pattern, sql))
    if unqualified_is_student:
        referenced_columns.update(_unqualified_select_columns(sql))
    return referenced_columns - ALLOWED_STUDENT_COLUMNS


def selects_student_data(sql: str, student_aliases: set[str]) -> bool:
    unqualified_is_student = _is_single_table_student_query(sql)
    ast = _parse_sql(sql)
    if ast:
        for select in ast.find_all(exp.Select):
            for projection in select.expressions:
                if unqualified_is_student and isinstance(projection, exp.Star):
                    return True
                if isinstance(projection, exp.Column):
                    if isinstance(projection.this, exp.Star) and projection.table.lower() in student_aliases:
                        return True
                for col in projection.find_all(exp.Column):
                    if _is_student_column(col, student_aliases, unqualified_is_student):
                        return True
        return False

    # Fallback to regex
    select_match = re.search(r"\bselect\b(.*?)\bfrom\b", sql, flags=re.DOTALL)
    if not select_match:
        return False
    select_clause = select_match.group(1)
    if unqualified_is_student and select_clause.strip():
        return True
    for alias in student_aliases:
        if re.search(rf"\b{re.escape(alias)}\.\*", select_clause):
            return True
        if re.search(rf"\b{re.escape(alias)}\.[a-z_][a-z0-9_]*\b", select_clause):
            return True
    return False


def has_scoped_student_filter(sql: str, table_aliases: set[str], requested_student_id: str | None) -> bool:
    ast = _parse_sql(sql)
    allowed_rhs_patterns = set(ALLOWED_STUDENT_ID_PLACEHOLDERS)
    if requested_student_id is not None:
        allowed_rhs_patterns.add(str(requested_student_id))
        allowed_rhs_patterns.add(f"'{requested_student_id}'")
        allowed_rhs_patterns.add(f'"{requested_student_id}"')

    # An unqualified `student_id` can only belong to the table being checked when the query
    # references no other table; multi-table queries must qualify the column.
    single_table_query = len(extract_table_references(sql)) == 1

    if ast:
        for eq in ast.find_all(exp.EQ):
            left, right = eq.left, eq.right

            def is_student_id_col(node):
                if not isinstance(node, exp.Column) or node.name.lower() != "student_id":
                    return False
                qualifier = node.table.lower()
                return qualifier in table_aliases or (single_table_query and not qualifier)
                
            def matches_rhs(node):
                if isinstance(node, (exp.Literal, exp.Identifier, exp.Var, exp.Parameter)):
                    val = str(node.name)
                    return val in allowed_rhs_patterns or f"'{val}'" in allowed_rhs_patterns or f'"{val}"' in allowed_rhs_patterns
                unparsed = node.sql()
                return unparsed in allowed_rhs_patterns or f"'{unparsed}'" in allowed_rhs_patterns or f'"{unparsed}"' in allowed_rhs_patterns

            if is_student_id_col(left) and matches_rhs(right):
                return True
            if is_student_id_col(right) and matches_rhs(left):
                return True

    # Fallback to regex
    allowed_rhs_regex = [re.escape(placeholder) for placeholder in ALLOWED_STUDENT_ID_PLACEHOLDERS]
    if requested_student_id is not None:
        escaped_id = re.escape(str(requested_student_id))
        allowed_rhs_regex.extend([rf"'{escaped_id}'", rf'"{escaped_id}"', escaped_id])

    rhs_group = "|".join(allowed_rhs_regex)
    for alias in table_aliases:
        pattern = rf"\b{re.escape(alias)}\.student_id\s*=\s*(?:{rhs_group})(?![a-z0-9_])"
        if re.search(pattern, sql):
            return True
    if single_table_query:
        pattern = rf"(?<![a-z0-9_.])student_id\s*=\s*(?:{rhs_group})(?![a-z0-9_])"
        if re.search(pattern, sql):
            return True

    return False


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

    table_references = extract_table_references(sql_without_trailing_semicolon)
    if not table_references:
        return {"ok": False, "reason": "FROM 또는 JOIN 절이 필요합니다."}

    disallowed_tables = table_references - ALLOWED_TABLES
    if disallowed_tables:
        return {
            "ok": False,
            "reason": f"허용되지 않은 테이블 참조: {', '.join(sorted(disallowed_tables))}",
        }

    if "student" in table_references:
        student_aliases = extract_table_aliases(sql_without_trailing_semicolon, "student")

        disallowed_student_columns = find_disallowed_student_columns(sql_without_trailing_semicolon, student_aliases)
        if disallowed_student_columns:
            return {
                "ok": False,
                "reason": f"student에서 허용되지 않은 컬럼 참조: {', '.join(sorted(disallowed_student_columns))}",
            }

        # A student may read their own allowed columns; anything else keeps student filter-only.
        if selects_student_data(sql_without_trailing_semicolon, student_aliases) and not has_scoped_student_filter(
            sql_without_trailing_semicolon, student_aliases, requested_student_id
        ):
            return {"ok": False, "reason": "student 테이블은 필터 조건으로만 사용할 수 있습니다."}

    for table_name in STUDENT_SCOPED_TABLES & table_references:
        table_aliases = extract_table_aliases(sql_without_trailing_semicolon, table_name)
        if not has_scoped_student_filter(sql_without_trailing_semicolon, table_aliases, requested_student_id):
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
