import pytest

from backend.eval import grading
from backend.eval.grading import (
    check_required_columns,
    check_required_tables,
    check_structural,
    check_student_scoped,
    classify_failure,
    common_columns,
    compare_execution,
    grade_case,
    project_rows,
    soft_f1,
)


def test_check_required_tables_passes_when_all_present():
    sql = "SELECT * FROM student s JOIN required_subject r ON s.dept_code = r.dept_code LIMIT 50"
    ok, reason = check_required_tables(sql, ["student", "required_subject"])
    assert ok is True
    assert reason is None


def test_check_required_tables_fails_when_missing():
    sql = "SELECT * FROM student LIMIT 50"
    ok, reason = check_required_tables(sql, ["student", "required_subject"])
    assert ok is False
    assert "required_subject" in reason


def test_check_required_columns_passes_with_alias():
    sql = "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"
    ok, reason = check_required_columns(sql, ["student.grade"])
    assert ok is True
    assert reason is None


def test_check_required_columns_fails_when_column_absent():
    sql = "SELECT s.dept_code FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"
    ok, reason = check_required_columns(sql, ["student.grade"])
    assert ok is False
    assert "student.grade" in reason


def test_check_student_scoped_passes_with_matching_literal():
    sql = "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"
    ok, reason = check_student_scoped(sql, "202102671")
    assert ok is True
    assert reason is None


def test_check_student_scoped_fails_without_filter():
    sql = "SELECT s.grade FROM student AS s LIMIT 50"
    ok, reason = check_student_scoped(sql, "202102671")
    assert ok is False
    assert "스코프" in reason


def test_check_structural_runs_all_checks_in_order():
    structural_checks = {
        "required_tables": ["student"],
        "required_columns": ["student.grade"],
        "student_scoped": True,
    }
    good_sql = "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"
    ok, reason = check_structural(good_sql, structural_checks, "202102671")
    assert ok is True
    assert reason is None

    missing_table_sql = "SELECT 1 AS grade LIMIT 50"
    ok, reason = check_structural(missing_table_sql, structural_checks, "202102671")
    assert ok is False
    assert "student" in reason


def test_common_columns_returns_intersection():
    rows_a = [{"subject_code": "1214-3033", "enrolled": 40}]
    rows_b = [{"subject_code": "1214-3033", "capacity": 45}]
    assert common_columns(rows_a, rows_b) == ["subject_code"]


def test_common_columns_empty_when_no_rows():
    assert common_columns([], [{"a": 1}]) == []
    assert common_columns([{"a": 1}], []) == []


def test_project_rows_extracts_values_in_column_order():
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert project_rows(rows, ["b", "a"]) == [(2, 1), (4, 3)]


def test_compare_execution_matches_when_row_sets_equal_ignoring_order():
    reference_rows = [
        {"subject_code": "1214-3033", "section": "00"},
        {"subject_code": "1214-3033", "section": "01"},
    ]
    generated_rows = [
        {"subject_code": "1214-3033", "section": "01"},
        {"subject_code": "1214-3033", "section": "00"},
    ]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is True
    assert reason is None


def test_compare_execution_ignores_exact_duplicate_rows():
    reference_rows = [{"subject_code": "1214-3033", "section": "00"}]
    generated_rows = [
        {"subject_code": "1214-3033", "section": "00"},
        {"subject_code": "1214-3033", "section": "00"},
    ]
    ok, _ = compare_execution(reference_rows, generated_rows)
    assert ok is True


def test_compare_execution_detects_missing_row():
    reference_rows = [
        {"subject_code": "A", "section": "00"},
        {"subject_code": "B", "section": "00"},
    ]
    generated_rows = [{"subject_code": "A", "section": "00"}]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is False
    assert "누락" in reason


def test_compare_execution_detects_extra_row():
    reference_rows = [{"subject_code": "A", "section": "00"}]
    generated_rows = [
        {"subject_code": "A", "section": "00"},
        {"subject_code": "B", "section": "00"},
    ]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is False
    assert "추가" in reason


def test_compare_execution_both_empty_is_match():
    ok, reason = compare_execution([], [])
    assert ok is True
    assert reason is None


def test_compare_execution_no_matching_columns_fails():
    reference_rows = [{"course_count": 1}]
    generated_rows = [{"different_column": 2}]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is False
    assert "course_count" in reason


def test_compare_execution_reports_when_one_side_is_empty():
    reference_rows = [{"subject_code": "A"}, {"subject_code": "B"}]
    generated_rows = []
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is False
    assert "대응하는 컬럼" not in reason
    assert "2" in reason and "0" in reason


def test_compare_execution_order_sensitive_detects_reordering():
    reference_rows = [{"n": 1}, {"n": 2}]
    generated_rows = [{"n": 2}, {"n": 1}]
    ok, _ = compare_execution(reference_rows, generated_rows, order_sensitive=True)
    assert ok is False


def test_grade_case_expects_error_passes_when_pipeline_rejects():
    case = {"id": "x", "grading": "structural", "expects_error": True, "structural_checks": {}}
    result = {"error": "질문이 모호합니다.", "rejected": True}
    grade = grade_case(case, result)
    assert grade == {"ok": True, "reason": None}


def test_grade_case_expects_error_fails_when_sql_was_generated():
    case = {"id": "x", "grading": "structural", "expects_error": True, "structural_checks": {}}
    result = {"sql": "SELECT 1 LIMIT 50", "data": []}
    grade = grade_case(case, result)
    assert grade["ok"] is False


def test_grade_case_fails_when_unexpected_error_occurs():
    case = {"id": "x", "grading": "execution", "expects_error": False, "reference_sql": "SELECT 1"}
    result = {"error": "허용되지 않은 테이블 참조: foo"}
    grade = grade_case(case, result)
    assert grade["ok"] is False
    assert "예상치 못한 오류" in grade["reason"]


def test_grade_case_structural_delegates_to_check_structural():
    case = {
        "id": "x",
        "grading": "structural",
        "expects_error": False,
        "student_id": "202102671",
        "structural_checks": {"required_tables": ["student"], "student_scoped": True},
    }
    result = {"sql": "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"}
    grade = grade_case(case, result)
    assert grade == {"ok": True, "reason": None}


def test_grade_case_execution_uses_run_query_for_reference_sql(monkeypatch):
    monkeypatch.setattr(grading, "expand_reference_sql", lambda sql: sql)

    def fake_run_query(sql, params=None):
        assert sql == "SELECT subject_code FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%'"
        return [{"subject_code": "1214-3033"}]

    monkeypatch.setattr(grading, "run_query", fake_run_query)

    case = {
        "id": "x",
        "grading": "execution",
        "expects_error": False,
        "reference_sql": "SELECT subject_code FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%'",
        "order_sensitive": False,
    }
    result = {"sql": "SELECT subject_code FROM v_course_info WHERE dept_name = '컴퓨터융합학부'", "data": [{"subject_code": "1214-3033"}]}
    grade = grade_case(case, result)
    assert grade == {"ok": True, "reason": None, "soft_f1": 1.0}


def test_grade_case_handles_null_structural_checks_without_crashing():
    case = {
        "id": "x",
        "grading": "structural",
        "expects_error": False,
        "structural_checks": None,
    }
    result = {"sql": "SELECT 1 LIMIT 50", "data": []}
    grade = grade_case(case, result)
    assert isinstance(grade, dict)
    assert grade == {"ok": True, "reason": None}


def test_grade_case_unknown_grading_mode_raises():
    case = {"id": "x", "grading": "not-a-real-mode", "expects_error": False}
    result = {"sql": "SELECT 1", "data": []}
    try:
        grade_case(case, result)
        assert False, "ValueError를 기대했지만 예외가 발생하지 않았습니다."
    except ValueError:
        pass


def test_compare_execution_requires_identity_columns_present_in_reference():
    reference_rows = [{"subject_code": "A", "section": "00", "subject_name": "자료구조"}]
    generated_rows = [{"subject_name": "자료구조"}]

    ok, reason = compare_execution(reference_rows, generated_rows)

    assert ok is False
    assert "subject_code" in reason and "section" in reason


def test_compare_execution_compares_on_identity_columns_when_present():
    reference_rows = [
        {"subject_code": "A", "section": "00", "subject_name": "자료구조"},
        {"subject_code": "B", "section": "00", "subject_name": "자료구조"},
    ]
    generated_rows = [{"subject_code": "A", "section": "00", "subject_name": "자료구조"}]

    ok, _ = compare_execution(reference_rows, generated_rows)

    assert ok is False


def test_compare_execution_without_identity_columns_keeps_intersection_behaviour():
    assert compare_execution([{"course_count": 3}], [{"course_count": 3, "x": 1}]) == (True, None)


def test_soft_f1_is_one_for_equal_sets_and_zero_for_disjoint():
    rows = [{"subject_code": "A", "section": "00"}, {"subject_code": "B", "section": "00"}]

    assert soft_f1(rows, list(reversed(rows))) == 1.0
    assert soft_f1(rows, [{"subject_code": "C", "section": "00"}]) == 0.0


def test_soft_f1_gives_partial_credit():
    reference_rows = [{"subject_code": c, "section": "00"} for c in ("A", "B", "C", "D")]
    generated_rows = [{"subject_code": c, "section": "00"} for c in ("A", "B")]

    assert soft_f1(reference_rows, generated_rows) == 0.6667


def test_soft_f1_edge_cases():
    assert soft_f1([], []) == 1.0
    assert soft_f1([{"a": 1}], []) == 0.0
    assert soft_f1([{"a": 1}], [{"b": 2}]) == 0.0


def test_grade_case_expands_reference_sql_and_reports_soft_f1(monkeypatch):
    calls = []
    monkeypatch.setattr(grading, "expand_reference_sql", lambda sql: sql + " /*expanded*/")

    def fake_run_query(sql):
        calls.append(sql)
        return [{"subject_code": "A", "section": "00"}]

    monkeypatch.setattr(grading, "run_query", fake_run_query)
    case = {"id": "x", "grading": "execution", "reference_sql": "SELECT subject_code, section FROM v_course_info"}
    result = {"sql": "SELECT 1", "data": [{"subject_code": "A", "section": "00"}]}

    grade = grade_case(case, result)

    assert calls == ["SELECT subject_code, section FROM v_course_info /*expanded*/"]
    assert grade == {"ok": True, "reason": None, "soft_f1": 1.0}


@pytest.mark.parametrize("case, result, grade, expected", [
    ({"grading": "execution"}, {"data": [1]}, {"ok": True}, "ok"),
    ({"expects_error": True, "grading": "structural"}, {"sql": "SELECT 1"}, {"ok": False}, "reject_missed"),
    ({"grading": "execution"}, {"error": "UNKNOWN"}, {"ok": False}, "error"),
    ({"grading": "structural"}, {"sql": "SELECT 1"}, {"ok": False}, "structural_mismatch"),
    ({"grading": "execution"}, {"sql": "SELECT 1", "data": []}, {"ok": False}, "empty_result"),
    ({"grading": "execution"}, {"sql": "SELECT 1", "data": [{"a": 1}]}, {"ok": False}, "result_mismatch"),
])
def test_classify_failure(case, result, grade, expected):
    assert classify_failure(case, result, grade) == expected


# --- column matching (name first, then value multiset) ---

def test_compare_execution_fails_wrong_grouped_count_under_different_alias():
    ok, reason = compare_execution(
        [{"category": "A", "course_count": 3}],
        [{"category": "A", "count": 99}],
    )
    assert ok is False
    assert "course_count" in reason


def test_compare_execution_passes_correct_count_with_different_alias():
    assert compare_execution([{"course_count": 3}], [{"count": 3}]) == (True, None)


def test_compare_execution_fails_when_reference_column_absent_and_no_value_match():
    ok, reason = compare_execution(
        [{"subject_name": "자료구조", "professor": "김"}],
        [{"subject_name": "자료구조"}],
    )
    assert ok is False
    assert "professor" in reason


def test_compare_execution_ignores_extra_generated_columns():
    reference_rows = [{"subject_code": "A", "section": "00"}]
    generated_rows = [{"subject_code": "A", "section": "00", "professor": "김"}]
    assert compare_execution(reference_rows, generated_rows) == (True, None)


def test_compare_execution_prefers_name_match_over_value_match():
    # 'n' exists on both sides with different values; another generated column happens
    # to carry the reference values, but the same-name column must be used.
    ok, _ = compare_execution([{"n": 1}, {"n": 2}], [{"n": 5, "m": 1}, {"n": 6, "m": 2}])
    assert ok is False


def test_soft_f1_uses_column_matching_and_set_semantics():
    assert soft_f1([{"course_count": 3}], [{"count": 3}]) == 1.0
    assert soft_f1([{"course_count": 3}], [{"count": 99}]) == 0.0
    reference_rows = [{"subject_code": "A", "section": "00"}]
    duplicated = [{"subject_code": "A", "section": "00"}, {"subject_code": "A", "section": "00"}]
    assert soft_f1(reference_rows, duplicated) == 1.0


# --- LIMIT cap ---

def _numbered(n, offset=0):
    return [{"subject_code": f"S{i:03d}", "section": "00"} for i in range(offset, offset + n)]


def test_compare_execution_passes_truncated_subset_at_row_cap(monkeypatch):
    monkeypatch.delenv("T2S_ROW_CAP", raising=False)
    assert compare_execution(_numbered(80), _numbered(50)) == (True, None)


def test_compare_execution_fails_row_cap_result_that_is_not_a_subset(monkeypatch):
    monkeypatch.delenv("T2S_ROW_CAP", raising=False)
    generated = _numbered(49) + [{"subject_code": "ZZZ", "section": "00"}]
    ok, _ = compare_execution(_numbered(80), generated)
    assert ok is False


def test_compare_execution_row_cap_is_read_at_call_time(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "10")
    assert compare_execution(_numbered(80), _numbered(10)) == (True, None)
    ok, _ = compare_execution(_numbered(80), _numbered(50))
    assert ok is False


def test_compare_execution_short_subset_below_row_cap_still_fails(monkeypatch):
    monkeypatch.delenv("T2S_ROW_CAP", raising=False)
    ok, _ = compare_execution(_numbered(80), _numbered(49))
    assert ok is False


# --- reject grading ---

def test_grade_case_expects_error_requires_rejected_flag():
    case = {"id": "x", "grading": "structural", "expects_error": True, "structural_checks": {}}

    assert grade_case(case, {"error": "질문이 모호합니다.", "rejected": True}) == {"ok": True, "reason": None}

    grade = grade_case(case, {"error": "connection refused"})
    assert grade["ok"] is False
    assert grade["reason"]


def test_classify_failure_reject_missed_only_without_rejection():
    case = {"expects_error": True, "grading": "structural"}
    assert classify_failure(case, {"error": "timeout"}, {"ok": False}) == "reject_missed"
    assert classify_failure({"grading": "execution"}, {"error": "x", "rejected": True}, {"ok": False}) == "error"


def test_grade_case_unexpected_error_on_execution_case_scores_zero_soft_f1():
    case = {"id": "x", "grading": "execution", "expects_error": False, "reference_sql": "SELECT 1"}
    grade = grade_case(case, {"error": "boom"})
    assert grade["ok"] is False
    assert grade["soft_f1"] == 0.0


# --- student scoping ---

def _student_execution_case():
    return {"id": "x", "grading": "execution", "expects_error": False,
            "student_id": "202102671", "reference_sql": "SELECT 1"}


def test_grade_case_fails_unscoped_student_sql(monkeypatch):
    monkeypatch.setattr(grading, "expand_reference_sql", lambda sql: sql)
    monkeypatch.setattr(grading, "run_query", lambda sql: [{"grade": 3}])
    result = {"sql": "SELECT s.grade FROM student AS s LIMIT 50", "data": [{"grade": 3}]}

    grade = grade_case(_student_execution_case(), result)

    assert grade["ok"] is False
    assert "학생 범위 미지정" in grade["reason"]


def test_grade_case_fails_unscoped_enrollment_sql(monkeypatch):
    monkeypatch.setattr(grading, "expand_reference_sql", lambda sql: sql)
    monkeypatch.setattr(grading, "run_query", lambda sql: [{"n": 1}])
    sql = ("SELECT COUNT(*) AS n FROM enrollment AS e JOIN student AS s ON s.student_id = e.student_id "
           "WHERE s.student_id = '202102671' LIMIT 50")
    grade = grade_case(_student_execution_case(), {"sql": sql, "data": [{"n": 1}]})

    assert grade["ok"] is False
    assert "학생 범위 미지정" in grade["reason"]


def test_grade_case_accepts_scoped_student_sql(monkeypatch):
    monkeypatch.setattr(grading, "expand_reference_sql", lambda sql: sql)
    monkeypatch.setattr(grading, "run_query", lambda sql: [{"grade": 3}])
    for sql in (
        "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50",
        "SELECT s.grade FROM student AS s WHERE s.student_id = :student_id LIMIT 50",
    ):
        grade = grade_case(_student_execution_case(), {"sql": sql, "data": [{"grade": 3}]})
        assert grade["ok"] is True, sql


# --- infra errors ---

def test_grade_case_reports_reference_sql_failure_as_infra_error(monkeypatch):
    monkeypatch.setattr(grading, "expand_reference_sql", lambda sql: sql)

    def broken(sql):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(grading, "run_query", broken)
    case = {"id": "x", "grading": "execution", "expects_error": False, "reference_sql": "SELECT 1"}
    result = {"sql": "SELECT 1", "data": [{"a": 1}]}

    grade = grade_case(case, result)

    assert grade["ok"] is False
    assert grade["reason"].startswith("정답 SQL 실행 실패: ")
    assert "connection refused" in grade["reason"]
    assert classify_failure(case, result, grade) == "infra_error"


def test_capped_result_with_duplicate_rows_does_not_pass(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "3")
    reference = [{"subject_code": c, "section": "00"} for c in "ABCDE"]
    generated = [{"subject_code": "A", "section": "00"}] * 3

    ok, _ = compare_execution(reference, generated)

    assert ok is False


def test_capped_distinct_subset_still_passes(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "3")
    reference = [{"subject_code": c, "section": "00"} for c in "ABCDE"]
    generated = [{"subject_code": c, "section": "00"} for c in "ABC"]

    assert compare_execution(reference, generated) == (True, None)


def test_capped_renamed_column_matches_by_value_subset(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "2")
    reference = [{"course_count": n} for n in (1, 2, 3)]
    generated = [{"cnt": n} for n in (1, 2)]

    assert compare_execution(reference, generated) == (True, None)


def test_capped_renamed_column_is_not_matched_when_ambiguous(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "2")
    reference = [{"course_count": n} for n in (1, 2, 3)]
    generated = [{"a": 1, "b": 1}, {"a": 2, "b": 2}]

    ok, reason = compare_execution(reference, generated)

    assert ok is False and "course_count" in reason
