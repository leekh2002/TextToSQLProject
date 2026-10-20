import pytest

from backend.eval.grading import check_student_scope
from backend.validate import validate_generated_sql

STUDENT_ID = "202102671"
FILTER_ONLY = "student 테이블은 필터 조건으로만 사용할 수 있습니다."


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 1",
        "SELECT s.grade FROM student AS s WHERE s.student_id = %(student_id)s LIMIT 1",
        "SELECT student.grade, student.dept_code FROM student WHERE student.student_id = '202102671' LIMIT 1",
    ],
)
def test_scoped_select_of_allowed_student_columns_is_ok(sql):
    assert validate_generated_sql(sql, requested_student_id=STUDENT_ID) == {"ok": True, "reason": None}


def test_unscoped_select_of_student_columns_keeps_filter_only_message():
    result = validate_generated_sql("SELECT s.grade FROM student AS s LIMIT 50", requested_student_id=STUDENT_ID)
    assert result == {"ok": False, "reason": FILTER_ONLY}


def test_scoped_select_with_another_student_id_is_rejected():
    sql = "SELECT s.grade FROM student AS s WHERE s.student_id = '201900001' LIMIT 1"
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result == {"ok": False, "reason": FILTER_ONLY}


def test_select_of_non_allowed_student_column_is_rejected():
    sql = "SELECT s.name FROM student AS s WHERE s.student_id = '202102671' LIMIT 1"
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result["ok"] is False
    assert result["reason"] == "student에서 허용되지 않은 컬럼 참조: name"


def test_single_table_unqualified_student_id_scopes_student():
    sql = "SELECT grade FROM student WHERE student_id = '202102671' LIMIT 1"
    assert validate_generated_sql(sql, requested_student_id=STUDENT_ID) == {"ok": True, "reason": None}


def test_single_table_unqualified_student_id_scopes_enrollment():
    sql = "SELECT subject_code FROM enrollment WHERE student_id = '202102671' LIMIT 50"
    assert validate_generated_sql(sql, requested_student_id=STUDENT_ID) == {"ok": True, "reason": None}


def test_single_table_unqualified_student_id_with_wrong_id_is_rejected():
    sql = "SELECT subject_code FROM enrollment WHERE student_id = '201900001' LIMIT 50"
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result["ok"] is False


def test_two_table_query_with_unqualified_student_id_is_still_rejected():
    sql = (
        "SELECT e.subject_code FROM enrollment AS e JOIN subject AS sub ON sub.subject_code = e.subject_code "
        "WHERE student_id = '202102671' LIMIT 50"
    )
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result == {
        "ok": False,
        "reason": "enrollment를 사용할 때는 요청된 학생의 학번으로 범위를 고정해야 합니다.",
    }


def test_two_table_student_select_with_unqualified_student_id_is_rejected():
    sql = (
        "SELECT s.grade FROM student AS s JOIN department AS d ON d.dept_code = s.dept_code "
        "WHERE student_id = '202102671' LIMIT 1"
    )
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result == {"ok": False, "reason": FILTER_ONLY}


def test_grader_scope_check_accepts_single_table_unqualified_filter():
    ok, reason = check_student_scope(
        "SELECT COUNT(DISTINCT subject_code) FROM enrollment WHERE student_id = '202102671'", STUDENT_ID
    )
    assert (ok, reason) == (True, None)


def test_single_table_unqualified_non_allowed_column_is_rejected():
    sql = "SELECT name FROM student WHERE student_id = '202102671' LIMIT 1"
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result == {"ok": False, "reason": "student에서 허용되지 않은 컬럼 참조: name"}


def test_single_table_unqualified_unscoped_select_is_rejected():
    result = validate_generated_sql("SELECT grade FROM student LIMIT 1", requested_student_id=STUDENT_ID)
    assert result == {"ok": False, "reason": FILTER_ONLY}


def test_single_table_unqualified_scoped_select_of_allowed_columns_is_ok():
    sql = "SELECT grade, dept_code FROM student WHERE student_id = '202102671' LIMIT 1"
    assert validate_generated_sql(sql, requested_student_id=STUDENT_ID) == {"ok": True, "reason": None}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM student WHERE student_id = '202102671' LIMIT 1",
        "SELECT s.* FROM student AS s WHERE s.student_id = '202102671' LIMIT 1",
    ],
)
def test_scoped_star_select_of_student_is_rejected(sql):
    result = validate_generated_sql(sql, requested_student_id=STUDENT_ID)
    assert result == {"ok": False, "reason": "student에서 허용되지 않은 컬럼 참조: *"}


def test_scoped_count_star_on_student_is_ok():
    sql = "SELECT COUNT(*) AS n FROM student WHERE student_id = '202102671' LIMIT 1"
    assert validate_generated_sql(sql, requested_student_id=STUDENT_ID) == {"ok": True, "reason": None}
