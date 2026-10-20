import pytest

from backend.t2s.postprocess import STANDARD_COLUMNS, ensure_limit, is_course_row_query, normalize_projection


def test_standard_columns_are_the_twenty_course_columns():
    assert len(STANDARD_COLUMNS) == 20
    assert STANDARD_COLUMNS[:3] == ("course_year", "subject_code", "section")


@pytest.mark.parametrize("sql, expected", [
    ("SELECT subject_name FROM v_course_info WHERE dept_name LIKE '%컴%' LIMIT 50", True),
    ("SELECT c.subject_name FROM v_course_info AS c WHERE c.day_of_week = '목'", True),
    ("SELECT COUNT(*) FROM v_course_info", False),
    ("SELECT dept_name, COUNT(*) FROM v_course_info GROUP BY dept_name", False),
    ("SELECT s.grade FROM student s WHERE s.student_id = '1'", False),
    ("SELECT c.subject_name FROM v_course_info c JOIN department d ON c.dept_name = d.dept_name", False),
    ("SELECT subject_name, rank() OVER (ORDER BY enrolled) FROM v_course_info", False),
    ("SELECT subject_name FROM v_course_info UNION SELECT subject_name FROM subject", False),
    ("not sql at all", False),
])
def test_is_course_row_query(sql, expected):
    assert is_course_row_query(sql) is expected


def test_normalize_projection_uses_standard_columns_with_alias():
    sql = normalize_projection("SELECT c.subject_name FROM v_course_info AS c WHERE c.day_of_week = '목' LIMIT 50")

    assert sql.startswith("SELECT c.course_year, c.subject_code, c.section")
    assert "c.prereq_subject_names FROM v_course_info AS c WHERE c.day_of_week = '목' LIMIT 50" in sql


def test_normalize_projection_keeps_aliased_computed_columns_for_order_by():
    sql = normalize_projection(
        "SELECT subject_name, capacity - enrolled AS remain FROM v_course_info ORDER BY remain DESC LIMIT 5"
    )

    assert "prereq_subject_names, capacity - enrolled AS remain FROM v_course_info ORDER BY remain DESC LIMIT 5" in sql


def test_normalize_projection_drops_distinct_and_star():
    sql = normalize_projection("SELECT DISTINCT * FROM v_course_info WHERE target_year = 3")

    assert sql.startswith("SELECT v_course_info.course_year")
    assert "DISTINCT" not in sql


def test_normalize_projection_leaves_other_queries_untouched():
    sql = "SELECT COUNT(DISTINCT subject_code || '-' || section) AS course_count FROM v_course_info"

    assert normalize_projection(sql) == sql


def test_ensure_limit_adds_only_when_missing():
    assert ensure_limit("SELECT 1 FROM v_course_info", 50) == "SELECT 1 FROM v_course_info LIMIT 50"
    assert ensure_limit("SELECT 1 FROM v_course_info LIMIT 5", 50) == "SELECT 1 FROM v_course_info LIMIT 5"
    assert ensure_limit("garbage (", 50) == "garbage ("


def test_normalize_projection_leaves_positional_order_by_untouched():
    sql = "SELECT subject_name, credit_hours FROM v_course_info ORDER BY 2 DESC LIMIT 5"

    assert normalize_projection(sql) == sql


def test_normalize_projection_leaves_shadowing_alias_untouched():
    sql = "SELECT subject_name, credit_hours*2 AS credit_hours FROM v_course_info ORDER BY credit_hours DESC"

    assert normalize_projection(sql) == sql


def test_normalize_projection_normalizes_same_column_alias():
    sql = normalize_projection("SELECT c.credit_hours AS credit_hours FROM v_course_info c")

    assert sql.startswith("SELECT c.course_year, c.subject_code, c.section")
    assert sql.endswith("c.prereq_subject_names FROM v_course_info AS c")
    assert sql.count("credit_hours") == 1


def test_top_n_limit_detection():
    from backend.t2s.postprocess import top_n_limit

    assert top_n_limit("SELECT * FROM v_course_info ORDER BY capacity DESC LIMIT 3") == 3
    assert top_n_limit("SELECT * FROM v_course_info LIMIT 3") is None
    assert top_n_limit("SELECT * FROM v_course_info ORDER BY capacity") is None
    assert top_n_limit("not sql at all (") is None


def test_expand_top_n_course_rows_wraps_key_subquery():
    import sqlglot
    from sqlglot import exp

    from backend.t2s.postprocess import expand_top_n_course_rows, normalize_projection

    inner = normalize_projection(
        "SELECT * FROM v_course_info WHERE start_time < '12:00:00' ORDER BY capacity DESC LIMIT 1")
    wrapped = expand_top_n_course_rows(inner, 50)

    tree = sqlglot.parse_one(wrapped, read="postgres")
    assert isinstance(tree, exp.Select) and tree.args["limit"].expression.name == "50"
    join = tree.args["joins"][0]
    matched = join.this
    assert matched.alias == "matched"
    key_select = matched.this
    assert key_select.args["distinct"] is not None
    assert [e.sql() for e in key_select.expressions] == ["sub.subject_code", "sub.section"]
    sub = key_select.args["from_"].this
    assert sub.alias == "sub"
    assert sub.this.args["limit"].expression.name == "1" and sub.this.args["order"] is not None
    assert "IS NOT DISTINCT FROM" in wrapped and "c.start_time" in wrapped


def test_expand_top_n_course_rows_needs_key_columns_in_projection():
    from backend.t2s.postprocess import expand_top_n_course_rows

    assert expand_top_n_course_rows("SELECT subject_name FROM v_course_info ORDER BY 1 LIMIT 2", 50) is None
