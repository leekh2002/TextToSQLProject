"""Regression tests for student/enrollment scope bypasses in validate_generated_sql."""
import pytest

from backend.eval.grading import check_student_scope, check_student_scoped
from backend.eval.run_eval import is_rejection_error
from backend.validate import validate_generated_sql

STUDENT_ID = "202102671"
OK = {"ok": True, "reason": None}

BYPASSES = [
    "SELECT student_id, grade FROM student /* student_id = %(student_id)s */ LIMIT 50",
    "SELECT s.student_id, s.grade FROM student s /* s.student_id = %(student_id)s */ LIMIT 50",
    "SELECT grade FROM student WHERE dept_code <> 'student_id = 202102671' LIMIT 50",
    "SELECT grade FROM student -- student_id = '202102671'\nLIMIT 50",
    "SELECT grade FROM student WHERE student_id = '202102671' OR 1=1 LIMIT 50",
    "SELECT s.student_id, s.grade FROM student s WHERE s.student_id = '202102671' OR s.student_id = '202000001' LIMIT 50",
    "SELECT grade FROM student WHERE NOT (student_id = '202102671') LIMIT 50",
    "SELECT grade FROM student WHERE (student_id = '202102671') IS NOT TRUE LIMIT 50",
    "SELECT grade FROM student WHERE CASE WHEN student_id = '202102671' THEN false ELSE true END LIMIT 50",
    "SELECT s.grade FROM student s WHERE coalesce(s.student_id = '202102671', true) LIMIT 50",
    "SELECT grade FROM student WHERE student_id = '202102671' OR student_id <> '202102671' LIMIT 50",
    "SELECT grade FROM student WHERE student_id = '202102671' OR student_id LIKE '%' LIMIT 50",
    "SELECT s.grade FROM public.student s WHERE s.student_id = '202102671' OR 1=1 LIMIT 50",
    'SELECT "S".grade FROM student "S" WHERE "S".student_id = \'202102671\' OR 1=1 LIMIT 50',
    "SELECT GRADE FROM STUDENT WHERE STUDENT_ID = '202102671' OR 1=1 LIMIT 50;",
    "SELECT grade, count(*) FROM student WHERE student_id = '202102671' OR 1=1 GROUP BY grade HAVING count(*) > 0 LIMIT 50",
    "SELECT grade FROM student WHERE student_id = %(student_id)s OR true LIMIT 50",
    "SELECT student_id, grade FROM student WHERE student_id = '202102671' UNION SELECT student_id, grade FROM student LIMIT 50",
    "SELECT s2.student_id, s2.grade FROM student s1 JOIN student s2 ON true WHERE s1.student_id = '202102671' LIMIT 50",
    "SELECT s2.student_id, s2.grade FROM student s1, student s2 WHERE s1.student_id = '202102671' LIMIT 50",
    "SELECT s.grade, (SELECT string_agg(student_id, ',') FROM student) FROM student s WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT student_id, letter_grade FROM enrollment WHERE student_id = '202102671' OR 1=1 LIMIT 50",
    "SELECT e.student_id, e.letter_grade FROM enrollment e WHERE e.student_id = '202102671' OR 1=1 LIMIT 50",
    "SELECT e.student_id, e.letter_grade FROM enrollment e /* e.student_id = %(student_id)s */ LIMIT 50",
    "SELECT e2.student_id, e2.letter_grade FROM enrollment e JOIN enrollment e2 ON true WHERE e.student_id = '202102671' LIMIT 50",
    "SELECT s.grade FROM student AS s(student_id, admission_year, grade) WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT row_to_json(s) FROM student s JOIN department d ON s.dept_code = d.dept_code WHERE s.student_id = '202102671' OR 1=1 LIMIT 50",
    "SELECT row_to_json(s) FROM student s WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT grade, d.dept_name FROM student s JOIN department d ON s.dept_code = d.dept_code WHERE s.student_id = '202102671' OR 1=1 LIMIT 50",
    "SELECT admission_year FROM student s JOIN department d USING (dept_code) WHERE s.student_id = '202102671' OR 1=1 LIMIT 50",
    "SELECT o.student_id, o.grade FROM (SELECT student_id, grade FROM student) o JOIN student s ON true WHERE s.student_id = '202102671' LIMIT 50",
    "WITH x AS (SELECT student_id, grade FROM student) SELECT x.grade FROM x JOIN student s ON true WHERE s.student_id = '202102671' LIMIT 50",
    # Unparseable SQL that mentions student or enrollment.
    "SELECT grade FROM student WHERE student_id = '202102671' LIMIT 50 ))",
    "SELECT e.letter_grade FROM enrollment e WHERE e.student_id = '202102671' LIMIT 50 ))",
    "SELECT upper(name) FROM student WHERE student_id = '202102671' LIMIT 50 ))",
    # Further variants from the security review.
    "SELECT student_id, grade FROM student WHERE student_id IN ('202102671', '202000001') LIMIT 50",
    "SELECT grade FROM student WHERE '202102671' = student_id OR true LIMIT 50",
    "SELECT s.grade FROM student s WHERE s.student_id = '202102671' = false LIMIT 50",
    "SELECT grade FROM student WHERE (student_id = '202102671') = false LIMIT 50",
    "SELECT grade FROM student WHERE student_id::text = '202102671' OR true LIMIT 50",
    "SELECT t.* FROM (SELECT * FROM student) t WHERE t.student_id = '202102671' LIMIT 50",
    "SELECT t.student_id, t.grade FROM (SELECT student_id, grade FROM student) t LIMIT 50",
    "SELECT s FROM student s WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT to_jsonb(s.*) FROM student s WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT * FROM (SELECT s.grade, s.dept_code FROM student s WHERE s.student_id = '202102671') t JOIN student x ON true LIMIT 50",
    "SELECT e.student_id, e.letter_grade FROM enrollment e JOIN student s ON true "
    "WHERE s.student_id = '202102671' AND e.student_id = '202102671' OR true LIMIT 50",
    "SELECT e.student_id, s.grade FROM enrollment e JOIN student s ON e.student_id = s.student_id "
    "WHERE e.student_id = '202102671' LIMIT 50",
    "SELECT s.name FROM student s JOIN department d ON s.dept_code = d.dept_code WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT name FROM student s JOIN department d ON s.dept_code = d.dept_code WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT s.grade FROM student s WHERE s.student_id = '202102671' AND s.name = 'x' LIMIT 50",
    "SELECT s.grade FROM student s WHERE s.student_id = '202102671' ORDER BY s.name LIMIT 50",
    "SELECT s.grade FROM student s WHERE s.student_id = '202102671' AND EXISTS "
    "(SELECT 1 FROM student t WHERE t.student_id <> '202102671') LIMIT 50",
]


@pytest.mark.parametrize("requested", [STUDENT_ID, None])
@pytest.mark.parametrize("sql", BYPASSES)
def test_bypass_is_rejected(sql, requested):
    result = validate_generated_sql(sql, requested_student_id=requested)
    assert result["ok"] is False, sql
    assert result["reason"]


@pytest.mark.parametrize(
    "sql",
    [
        BYPASSES[0],
        BYPASSES[1],
        BYPASSES[2],
        BYPASSES[3],
        BYPASSES[4],
        BYPASSES[22],
        BYPASSES[23],
        "SELECT grade FROM student WHERE student_id = '202102671' LIMIT 50 ))",
    ],
)
def test_grader_scope_check_rejects_bypasses(sql):
    ok, reason = check_student_scope(sql, STUDENT_ID)
    assert ok is False, sql
    assert reason


def test_grader_structural_scope_rejects_comment_bypass():
    ok, _ = check_student_scoped(BYPASSES[1], STUDENT_ID)
    assert ok is False


def test_unparseable_sql_is_rejected_with_parse_reason():
    result = validate_generated_sql("SELECT grade FROM student WHERE student_id = '202102671' LIMIT 50 ))", STUDENT_ID)
    assert result == {"ok": False, "reason": "SQL을 해석할 수 없습니다."}


def test_unparseable_sql_without_student_is_also_rejected():
    result = validate_generated_sql("SELECT subject_code FROM subject LIMIT 50 ))")
    assert result == {"ok": False, "reason": "SQL을 해석할 수 없습니다."}


@pytest.mark.parametrize("table", ["student", "enrollment"])
def test_alias_column_list_is_rejected_as_safety_rejection(table):
    sql = f"SELECT x.a FROM {table} AS x(a, b) WHERE x.a = '202102671' LIMIT 50"
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result == {"ok": False, "reason": f"{table}에 열 별칭 목록을 지정할 수 없습니다."}
    assert is_rejection_error(result["reason"])


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT row_to_json(s) FROM student s WHERE s.student_id = '202102671' LIMIT 50",
        "SELECT to_jsonb(s.*) FROM student s WHERE s.student_id = '202102671' LIMIT 50",
        "SELECT t.* FROM (SELECT s.grade FROM student s WHERE s.student_id = '202102671') t LIMIT 50",
        "SELECT * FROM (SELECT s.grade FROM student s WHERE s.student_id = '202102671') t LIMIT 50",
    ],
)
def test_whole_row_reference_to_student_is_rejected_as_star(sql):
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result == {"ok": False, "reason": "student에서 허용되지 않은 컬럼 참조: *"}


LEGITIMATE = [
    # scoped single-table and qualified student self-read
    "SELECT grade FROM student WHERE student_id = '202102671' LIMIT 50",
    "SELECT grade FROM student WHERE student_id = %(student_id)s LIMIT 50",
    "SELECT s.grade, s.admission_year FROM student AS s WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT s.grade FROM student AS s WHERE s.student_id = %(student_id)s LIMIT 50",
    "SELECT s.grade FROM public.student AS s WHERE (s.student_id = '202102671') LIMIT 50",
    "SELECT s.grade FROM student AS s WHERE s.grade > 1 AND (s.dept_code = 'D094' AND '202102671' = s.student_id) LIMIT 50",
    "SELECT COUNT(*) AS n FROM student WHERE student_id = '202102671' ORDER BY n LIMIT 1",
    # enrollment
    "SELECT e.subject_code FROM enrollment e WHERE e.student_id = '202102671' LIMIT 50",
    "SELECT sub.subject_name, e.letter_grade FROM enrollment AS e JOIN subject AS sub "
    "ON sub.subject_code = e.subject_code WHERE e.student_id = '202102671' LIMIT 50",
    "SELECT sub.subject_name FROM subject AS sub JOIN enrollment AS e "
    "ON e.subject_code = sub.subject_code AND e.student_id = %(student_id)s LIMIT 50",
    # the pipeline's exclusion wrapper
    "SELECT c.subject_code, c.subject_name FROM v_course_info AS c WHERE c.dept_name = '컴퓨터융합학부' "
    "AND NOT EXISTS (SELECT 1 FROM enrollment AS a WHERE a.student_id = '202102671' "
    "AND a.subject_code = c.subject_code) LIMIT 50",
    "SELECT c.* FROM v_course_info AS c JOIN (SELECT DISTINCT v.subject_code, v.section FROM v_course_info AS v "
    "WHERE v.day_of_week = '목') AS matched_courses ON c.subject_code = matched_courses.subject_code "
    "AND c.section IS NOT DISTINCT FROM matched_courses.section "
    "WHERE NOT EXISTS (\n    SELECT 1\n    FROM enrollment AS a\n    WHERE a.student_id = '202102671'\n"
    "      AND a.subject_code = c.subject_code\n) ORDER BY c.subject_code LIMIT 200",
    # student JOIN department for "my department"
    "SELECT d.dept_name FROM student AS s JOIN department AS d ON d.dept_code = s.dept_code "
    "WHERE s.student_id = '202102671' LIMIT 50",
    "SELECT d.dept_name, s.grade FROM student AS s JOIN department AS d ON d.dept_code = s.dept_code "
    "WHERE s.student_id = %(student_id)s LIMIT 50",
]


@pytest.mark.parametrize("sql", LEGITIMATE)
def test_legitimate_scoped_form_passes(sql):
    assert validate_generated_sql(sql, requested_student_id=STUDENT_ID) == OK


@pytest.mark.parametrize("sql", [s for s in LEGITIMATE if "%(student_id)s" in s])
def test_placeholder_scoped_form_passes_without_requested_id(sql):
    assert validate_generated_sql(sql, requested_student_id=None) == OK


@pytest.mark.parametrize("sql", LEGITIMATE)
def test_grader_scope_check_accepts_legitimate_form(sql):
    assert check_student_scope(sql, STUDENT_ID) == (True, None)


def test_literal_scope_without_requested_id_is_rejected():
    sql = "SELECT e.subject_code FROM enrollment e WHERE e.student_id = '202102671' LIMIT 50"
    assert validate_generated_sql(sql, requested_student_id=None)["ok"] is False


def test_non_student_query_still_passes():
    sql = (
        "SELECT c.* FROM v_course_info AS c JOIN (SELECT DISTINCT v_course_info.subject_code, v_course_info.section "
        "FROM v_course_info WHERE dept_name = '컴퓨터융합학부' AND target_year = 3) AS matched_courses "
        "ON c.subject_code = matched_courses.subject_code "
        "AND c.section IS NOT DISTINCT FROM matched_courses.section ORDER BY c.subject_code LIMIT 200"
    )
    assert validate_generated_sql(sql) == OK


OUTER_JOIN_BYPASSES = [
    "SELECT s.grade FROM department d RIGHT JOIN student s ON s.student_id = '202102671' LIMIT 50",
    "SELECT s.grade FROM department d FULL JOIN student s ON s.student_id = '202102671' LIMIT 50",
    "SELECT e.letter_grade FROM subject j RIGHT JOIN enrollment e ON e.student_id = '202102671' LIMIT 50",
    "SELECT e.letter_grade FROM subject j FULL OUTER JOIN enrollment e ON e.student_id = %(student_id)s LIMIT 50",
    "SELECT s.grade FROM department d RIGHT OUTER JOIN student s ON s.student_id = %(student_id)s LIMIT 50",
    "SELECT s.grade FROM student s LEFT JOIN department d ON s.student_id = '202102671' LIMIT 50",
    "SELECT e.letter_grade FROM enrollment e LEFT JOIN subject j ON e.student_id = %(student_id)s LIMIT 50",
    "SELECT s.grade FROM student s FULL JOIN department d ON s.student_id = '202102671' LIMIT 50",
    "SELECT s.grade FROM department d NATURAL JOIN student s LIMIT 50",
    "SELECT s.grade FROM department d CROSS JOIN student s LIMIT 50",
    "SELECT s.grade FROM department d JOIN student s USING (dept_code) LIMIT 50",
    "SELECT e.letter_grade FROM subject j NATURAL RIGHT JOIN enrollment e LIMIT 50",
    "SELECT e.letter_grade FROM subject j RIGHT JOIN enrollment e USING (subject_code) LIMIT 50",
]


@pytest.mark.parametrize("requested", [STUDENT_ID, None])
@pytest.mark.parametrize("sql", OUTER_JOIN_BYPASSES)
def test_outer_join_preserved_side_is_not_scoped_by_on(sql, requested):
    result = validate_generated_sql(sql, requested_student_id=requested)
    assert result["ok"] is False, sql


@pytest.mark.parametrize("sql", OUTER_JOIN_BYPASSES[:4])
def test_grader_rejects_outer_join_preserved_side(sql):
    assert check_student_scope(sql, STUDENT_ID)[0] is False


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT d.dept_name FROM department d INNER JOIN student s ON s.student_id = '202102671' "
        "AND s.dept_code = d.dept_code LIMIT 50",
        "SELECT j.subject_name FROM subject j LEFT JOIN enrollment e ON e.subject_code = j.subject_code "
        "AND e.student_id = '202102671' LIMIT 50",
        "SELECT s.grade FROM department d RIGHT JOIN student s ON s.dept_code = d.dept_code "
        "WHERE s.student_id = '202102671' LIMIT 50",
        "SELECT s.grade FROM department d JOIN student s USING (dept_code) WHERE s.student_id = '202102671' LIMIT 50",
    ],
)
def test_inner_or_nullable_side_join_scope_passes(sql):
    assert validate_generated_sql(sql, requested_student_id=STUDENT_ID) == OK


DANGEROUS_FUNCTION_SQL = [
    ("SELECT subject_code FROM subject WHERE pg_sleep(5) IS NOT NULL LIMIT 50", "pg_sleep"),
    ("SELECT pg_read_file('/etc/passwd') FROM subject LIMIT 50", "pg_read_file"),
    ("SELECT subject_code FROM subject WHERE subject_code IN (SELECT set_config('a', 'b', false)) LIMIT 50", "set_config"),
    ("SELECT table_to_xml('student', true, false, '') FROM subject LIMIT 50", "table_to_xml"),
    ("SELECT dblink('host=x', 'select 1') FROM subject LIMIT 50", "dblink"),
    ("SELECT current_setting('x') FROM subject LIMIT 50", "current_setting"),
    ("SELECT pg_catalog.pg_sleep(5) FROM subject LIMIT 50", "pg_sleep"),
    ("SELECT lo_import('/etc/passwd') FROM subject LIMIT 50", "lo_import"),
    ("SELECT version() FROM subject LIMIT 50", "current_version"),
    ("SELECT query_to_xml('select * from student', true, false, '') FROM subject LIMIT 50", "query_to_xml"),
    ("SELECT txid_current() FROM subject LIMIT 50", "txid_current"),
]


@pytest.mark.parametrize("sql,name", DANGEROUS_FUNCTION_SQL)
def test_system_function_calls_are_rejected(sql, name):
    result = validate_generated_sql(sql, STUDENT_ID)

    assert result == {"ok": False, "reason": f"허용되지 않은 함수 호출: {name}"}
    assert is_rejection_error(result["reason"])


ORDINARY_FUNCTION_SQL = [
    "SELECT COUNT(*), AVG(credit_hours), MAX(credit_hours), MIN(credit_hours), SUM(credit_hours) FROM v_course_info LIMIT 50",
    "SELECT COALESCE(professor, '-'), LOWER(subject_name), UPPER(subject_name), LENGTH(subject_name) FROM v_course_info LIMIT 50",
    "SELECT SUBSTRING(subject_code, 1, 3), SPLIT_PART(subject_code, '-', 1), ROUND(AVG(credit_hours), 1) FROM v_course_info GROUP BY subject_code LIMIT 50",
    "SELECT CAST(credit_hours AS TEXT), EXTRACT(HOUR FROM start_time) FROM v_course_info LIMIT 50",
    "SELECT dept_name, STRING_AGG(subject_name, ',') FROM v_course_info GROUP BY dept_name LIMIT 50",
]


@pytest.mark.parametrize("sql", ORDINARY_FUNCTION_SQL)
def test_ordinary_functions_are_still_accepted(sql):
    assert validate_generated_sql(sql, STUDENT_ID) == OK


@pytest.mark.parametrize("sql,name", [
    ('SELECT U&"\0070g_sleep"(1) FROM subject LIMIT 50', "U&"),
    ("SELECT u&'abc' FROM subject LIMIT 50", "U&"),
    ("SELECT subject_code FROM subject WHERE subject_code = (TABLE student) LIMIT 50", "TABLE"),
    ("SELECT subject_code FROM subject UNION ALL TABLE student LIMIT 50", "TABLE"),
])
def test_escaped_identifiers_and_table_command_are_rejected(sql, name):
    result = validate_generated_sql(sql, STUDENT_ID)

    assert result == {"ok": False, "reason": f"허용되지 않은 구문: {name}"}
    assert is_rejection_error(result["reason"])
