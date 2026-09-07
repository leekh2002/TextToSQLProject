import json
from pathlib import Path

from backend.eval import run_eval


def test_load_cases_reads_json_array(tmp_path):
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps([{"id": "a"}]), encoding="utf-8")
    cases = run_eval.load_cases(cases_file)
    assert cases == [{"id": "a"}]


def test_run_case_calls_process_and_grades(monkeypatch):
    captured = {}

    def fake_process(query, exclude_completed_courses=False, student_id=None):
        captured["args"] = (query, exclude_completed_courses, student_id)
        return {"sql": "SELECT 1 LIMIT 50", "data": []}

    def fake_grade_case(case, result):
        return {"ok": True, "reason": None}

    monkeypatch.setattr(run_eval, "process", fake_process)
    monkeypatch.setattr(run_eval, "grade_case", fake_grade_case)

    case = {
        "id": "x",
        "category": "course_filter",
        "query": "테스트 질의",
        "student_id": "202102671",
        "exclude_completed_courses": True,
        "reference_sql": None,
    }
    record = run_eval.run_case(case)

    assert captured["args"] == ("테스트 질의", True, "202102671")
    assert record == {
        "id": "x",
        "category": "course_filter",
        "query": "테스트 질의",
        "ok": True,
        "reason": None,
        "sql": "SELECT 1 LIMIT 50",
        "reference_sql": None,
        "error": None,
    }


def test_run_case_records_exception_from_grading_without_crashing(monkeypatch):
    monkeypatch.setattr(run_eval, "process", lambda query, exclude_completed_courses=False, student_id=None: {"sql": "SELECT 1", "data": []})

    def failing_grade_case(case, result):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_eval, "grade_case", failing_grade_case)

    case = {"id": "x", "category": "course_filter", "query": "q", "reference_sql": None}
    record = run_eval.run_case(case)
    assert record["ok"] is False
    assert "boom" in record["reason"]


def test_run_case_records_exception_from_process_without_crashing(monkeypatch):
    def failing_process(query, exclude_completed_courses=False, student_id=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_eval, "process", failing_process)

    case = {"id": "x", "category": "course_filter", "query": "q", "reference_sql": None}
    record = run_eval.run_case(case)
    assert record["ok"] is False
    assert "boom" in record["reason"]


def test_run_case_treats_database_url_warning_as_hard_failure(monkeypatch):
    def fake_process(query, exclude_completed_courses=False, student_id=None):
        return {
            "warning": "DATABASE_URL is not set. SQL only mode is active.",
            "data": [],
            "sql": "SELECT 1",
        }

    def should_not_be_called(case, result):
        raise AssertionError("should not be called")

    monkeypatch.setattr(run_eval, "process", fake_process)
    monkeypatch.setattr(run_eval, "grade_case", should_not_be_called)

    case = {"id": "x", "category": "course_filter", "query": "q", "reference_sql": None}
    record = run_eval.run_case(case)
    assert record["ok"] is False
    assert "DATABASE_URL" in record["reason"]


def test_summarize_computes_overall_and_per_category_accuracy():
    records = [
        {"category": "a", "ok": True},
        {"category": "a", "ok": False},
        {"category": "b", "ok": True},
    ]
    summary = run_eval.summarize(records)
    assert summary["overall"] == {"passed": 2, "total": 3, "accuracy": 66.7}
    assert summary["by_category"]["a"] == {"passed": 1, "total": 2, "accuracy": 50.0}
    assert summary["by_category"]["b"] == {"passed": 1, "total": 1, "accuracy": 100.0}


def test_write_report_file_creates_json_with_summary_and_records(tmp_path):
    summary = {"overall": {"passed": 1, "total": 1, "accuracy": 100.0}, "by_category": {}}
    records = [{"id": "x", "ok": True}]
    report_path = run_eval.write_report_file(summary, records, tmp_path)
    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["summary"] == summary
    assert saved["records"] == records


def test_main_returns_nonzero_when_below_min_accuracy(monkeypatch, tmp_path, capsys):
    cases = [
        {"id": "a", "category": "c", "query": "q1", "reference_sql": None},
        {"id": "b", "category": "c", "query": "q2", "reference_sql": None},
    ]
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")

    monkeypatch.setattr(run_eval, "GOLDEN_QUERIES_PATH", cases_file)
    monkeypatch.setattr(run_eval, "process", lambda query, exclude_completed_courses=False, student_id=None: {"sql": "SELECT 1", "data": []})

    call_count = {"n": 0}

    def fake_grade_case(case, result):
        call_count["n"] += 1
        return {"ok": call_count["n"] == 1, "reason": None if call_count["n"] == 1 else "실패"}

    monkeypatch.setattr(run_eval, "grade_case", fake_grade_case)

    exit_code = run_eval.main(["--report-dir", str(tmp_path / "reports"), "--min-accuracy", "80"])
    assert exit_code == 1

    exit_code_ok = run_eval.main(["--report-dir", str(tmp_path / "reports"), "--min-accuracy", "0"])
    assert exit_code_ok == 0


def test_main_filters_by_category(monkeypatch, tmp_path):
    cases = [
        {"id": "a", "category": "keep", "query": "q1", "reference_sql": None},
        {"id": "b", "category": "skip", "query": "q2", "reference_sql": None},
    ]
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")

    monkeypatch.setattr(run_eval, "GOLDEN_QUERIES_PATH", cases_file)

    seen_ids = []

    def fake_process(query, exclude_completed_courses=False, student_id=None):
        return {"sql": "SELECT 1", "data": []}

    def fake_grade_case(case, result):
        seen_ids.append(case["id"])
        return {"ok": True, "reason": None}

    monkeypatch.setattr(run_eval, "process", fake_process)
    monkeypatch.setattr(run_eval, "grade_case", fake_grade_case)

    run_eval.main(["--filter", "keep", "--report-dir", str(tmp_path / "reports")])
    assert seen_ids == ["a"]
