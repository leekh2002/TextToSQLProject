import json
from pathlib import Path

import pytest

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
        return {"sql": "SELECT 1 LIMIT 50", "data": [{"a": 1}]}

    monkeypatch.setattr(run_eval, "process", fake_process)
    monkeypatch.setattr(run_eval, "grade_case", lambda case, result: {"ok": True, "reason": None, "soft_f1": 1.0})

    case = {
        "id": "x",
        "category": "course_filter",
        "query": "테스트 질의",
        "grading": "execution",
        "student_id": "202102671",
        "exclude_completed_courses": True,
        "reference_sql": None,
    }
    record = run_eval.run_case(case)

    assert captured["args"] == ("테스트 질의", True, "202102671")
    latency = record.pop("latency_ms")
    assert isinstance(latency, int) and latency >= 0
    assert record == {
        "id": "x",
        "category": "course_filter",
        "query": "테스트 질의",
        "ok": True,
        "reason": None,
        "sql": "SELECT 1 LIMIT 50",
        "reference_sql": None,
        "error": None,
        "failure_type": "ok",
        "soft_f1": 1.0,
        "empty_gold": False,
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


def test_run_case_passes_gold_values_only_in_decoupled_mode(monkeypatch):
    seen = []

    def pipeline(query, *, exclude_completed_courses=False, student_id=None, value_hints=None):
        seen.append(value_hints)
        return {"sql": "SELECT 1", "data": []}

    monkeypatch.setattr(run_eval, "grade_case", lambda case, result: {"ok": False, "reason": "x"})
    gold = [{"column": "dept_name", "value": "공과대학 컴퓨터융합학부"}]
    case = {"id": "x", "category": "c", "query": "q", "grading": "execution", "gold_values": gold}

    run_eval.run_case(case, pipeline=pipeline)
    run_eval.run_case(case, pipeline=pipeline, decoupled=True)

    assert seen == [None, gold]


def test_run_case_records_pipeline_exception_as_failure():
    def broken(query, **kwargs):
        raise RuntimeError("ollama down")

    record = run_eval.run_case({"id": "x", "category": "c", "query": "q", "grading": "execution"}, pipeline=broken)

    assert record["ok"] is False
    assert record["failure_type"] == "exception"
    assert "ollama down" in record["reason"]


def test_percentile_nearest_rank():
    values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]

    assert run_eval.percentile(values, 50) == 500
    assert run_eval.percentile(values, 95) == 1000
    assert run_eval.percentile([], 50) is None


def _record(category, ok, failure_type="ok", latency=100, f1=None, empty=False):
    return {"category": category, "ok": ok, "failure_type": failure_type,
            "latency_ms": latency, "soft_f1": f1, "empty_gold": empty}


def test_summarize_separates_empty_gold_and_reports_extras():
    records = [
        _record("a", True, latency=100, f1=1.0),
        _record("a", False, "result_mismatch", latency=300, f1=0.5),
        _record("b", True, latency=200),
        _record("b", True, latency=900, empty=True),
    ]

    summary = run_eval.summarize(records)

    assert summary["overall"] == {"passed": 2, "total": 3, "accuracy": 66.7}
    assert summary["by_category"]["b"] == {"passed": 1, "total": 1, "accuracy": 100.0}
    assert summary["empty_gold"] == {"passed": 1, "total": 1}
    assert summary["failure_types"] == {"ok": 3, "result_mismatch": 1}
    assert summary["latency_ms"] == {"p50": 200, "p95": 900}
    assert summary["mean_soft_f1"] == 0.75


def test_collect_config_snapshots_t2s_environment(monkeypatch):
    monkeypatch.setenv("T2S_CANDIDATES", "5")
    monkeypatch.setenv("OLLAMA_MODEL", "m")

    config = run_eval.collect_config("v1", True)

    assert config["pipeline"] == "v1"
    assert config["decoupled"] is True
    assert config["env"]["T2S_CANDIDATES"] == "5"
    assert config["env"]["OLLAMA_MODEL"] == "m"


def test_write_report_file_includes_config(tmp_path):
    path = run_eval.write_report_file({"overall": {}}, [], tmp_path, config={"pipeline": "v1"})

    assert json.loads(path.read_text(encoding="utf-8"))["config"] == {"pipeline": "v1"}


def test_main_rejects_unknown_pipeline(capsys):
    with pytest.raises(SystemExit):
        run_eval.main(["--pipeline", "nope"])
