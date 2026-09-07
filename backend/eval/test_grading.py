from backend.eval.grading import (
    check_required_columns,
    check_required_tables,
    check_structural,
    check_student_scoped,
    common_columns,
    compare_execution,
    project_rows,
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


def test_compare_execution_no_common_columns_fails():
    reference_rows = [{"subject_code": "A"}]
    generated_rows = [{"different_column": "A"}]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is False
    assert "겹치지 않습니다" in reason


def test_compare_execution_order_sensitive_detects_reordering():
    reference_rows = [{"n": 1}, {"n": 2}]
    generated_rows = [{"n": 2}, {"n": 1}]
    ok, _ = compare_execution(reference_rows, generated_rows, order_sensitive=True)
    assert ok is False
