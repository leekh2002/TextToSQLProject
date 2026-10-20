import hashlib
import json
import os
from pathlib import Path

import pytest

from backend.eval import run_eval


@pytest.fixture(autouse=True)
def _restore_vector_cache_env(monkeypatch):
    # main() sets VECTOR_CACHE_ENABLED; registering it here makes monkeypatch restore it.
    monkeypatch.setenv("VECTOR_CACHE_ENABLED", os.environ.get("VECTOR_CACHE_ENABLED", "1"))


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
        "cache_hit": None,
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
    # The first record (100ms) is the warm-up and is excluded: percentiles over 300, 200, 900.
    assert summary["latency_ms"] == {"p50": 300, "p95": 900, "warmup_excluded_ms": 100}
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


# --- vector cache is disabled during evaluation ---

def _write_cases(tmp_path, monkeypatch, cases=None):
    cases = cases or [{"id": "a", "category": "c", "query": "q1", "grading": "execution", "reference_sql": None}]
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")
    monkeypatch.setattr(run_eval, "GOLDEN_QUERIES_PATH", cases_file)
    monkeypatch.setattr(run_eval, "grade_case", lambda case, result: {"ok": True, "reason": None})
    return cases_file


def _env_recording_pipeline(seen):
    def pipeline(query, *, exclude_completed_courses=False, student_id=None, value_hints=None):
        seen.append(os.environ.get("VECTOR_CACHE_ENABLED"))
        return {"sql": "SELECT 1", "data": [], "cache_hit": False}
    pipeline.accepts_value_hints = False
    return pipeline


def test_main_disables_vector_cache_before_calling_the_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("VECTOR_CACHE_ENABLED", "1")
    _write_cases(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setitem(run_eval.PIPELINES, "v1", _env_recording_pipeline(seen))

    run_eval.main(["--report-dir", str(tmp_path / "reports")])

    assert seen == ["0"]


def test_main_keeps_vector_cache_with_use_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("VECTOR_CACHE_ENABLED", "1")
    _write_cases(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setitem(run_eval.PIPELINES, "v1", _env_recording_pipeline(seen))

    run_eval.main(["--use-cache", "--report-dir", str(tmp_path / "reports")])

    assert seen == ["1"]


def test_run_case_records_cache_hit():
    case = {"id": "x", "category": "c", "query": "q", "grading": "execution"}
    hit = run_eval.run_case(case, pipeline=lambda q, **kw: {"sql": "SELECT 1", "data": [], "cache_hit": True})
    absent = run_eval.run_case(case, pipeline=lambda q, **kw: {"sql": "SELECT 1", "data": []})

    assert hit["cache_hit"] is True
    assert absent["cache_hit"] is None


# --- rejection contract of the v1 adapter ---

def _process_returning(result):
    return lambda query, exclude_completed_courses=False, student_id=None: result


@pytest.mark.parametrize("message", [
    "질문이 모호합니다.",
    "SELECT 문만 허용됩니다.",
    "여러 문장은 허용되지 않습니다.",
    "금지 키워드 포함: delete",
    "허용되지 않은 테이블 참조: users",
    "student에서 허용되지 않은 컬럼 참조: name",
    "student 테이블은 필터 조건으로만 사용할 수 있습니다.",
    "enrollment를 사용할 때는 요청된 학생의 학번으로 범위를 고정해야 합니다.",
])
def test_v1_pipeline_marks_rejections(monkeypatch, message):
    monkeypatch.setattr(run_eval, "process", _process_returning({"error": message}))

    result = run_eval.v1_pipeline("q")

    assert result["rejected"] is True
    assert result["error"] == message


def test_v1_pipeline_does_not_mark_other_errors_as_rejections(monkeypatch):
    monkeypatch.setattr(run_eval, "process", _process_returning({"error": "relation foo does not exist"}))
    assert run_eval.v1_pipeline("q").get("rejected") is not True

    monkeypatch.setattr(run_eval, "process", _process_returning({"error": "기본 LIMIT가 필요합니다."}))
    assert run_eval.v1_pipeline("q").get("rejected") is not True

    monkeypatch.setattr(run_eval, "process", _process_returning({"sql": "SELECT 1", "data": []}))
    assert "rejected" not in run_eval.v1_pipeline("q")


def test_v1_pipeline_maps_raised_safety_rejection(monkeypatch):
    def raising(query, exclude_completed_courses=False, student_id=None):
        raise Exception("금지 키워드 포함: drop")

    monkeypatch.setattr(run_eval, "process", raising)

    assert run_eval.v1_pipeline("q") == {"error": "금지 키워드 포함: drop", "rejected": True}


def test_v1_pipeline_reraises_other_exceptions(monkeypatch):
    def raising(query, exclude_completed_courses=False, student_id=None):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(run_eval, "process", raising)

    with pytest.raises(RuntimeError):
        run_eval.v1_pipeline("q")


def test_rejection_patterns_track_validate_reasons():
    from backend.validate import validate_generated_sql

    probes = [
        ("update subject set a = 1", None),
        ("select 1 from subject; select 2 from subject", None),
        ("select * from subject where x = 1 or drop_me() is null and 1 = 1 or true limit 50 -- drop", None),
        ("select * from users limit 50", None),
        ("select s.name from student as s where s.student_id = :student_id limit 50", None),
        ("select s.grade from student as s where s.student_id = :student_id limit 50", None),
        ("select * from enrollment as e limit 50", "202102671"),
    ]
    seen_reasons = set()
    for sql, student_id in probes:
        reason = validate_generated_sql(sql, requested_student_id=student_id)["reason"]
        assert reason, sql
        assert run_eval.is_rejection_error(reason), reason
        seen_reasons.add(reason.split(":")[0])
    assert len(seen_reasons) == len(probes)


def test_v1_declares_it_does_not_accept_value_hints():
    assert run_eval.v1_pipeline.accepts_value_hints is False


# --- robustness ---

def test_run_case_guards_against_non_dict_result():
    case = {"id": "x", "category": "c", "query": "q", "grading": "execution"}
    record = run_eval.run_case(case, pipeline=lambda q, **kw: "not a dict")

    assert record["ok"] is False
    assert record["failure_type"] == "exception"
    assert record["soft_f1"] == 0.0


def test_run_case_scores_zero_soft_f1_for_failed_execution_cases_only():
    def broken(query, **kwargs):
        raise RuntimeError("ollama down")

    execution = run_eval.run_case({"id": "x", "category": "c", "query": "q", "grading": "execution"}, pipeline=broken)
    reject = run_eval.run_case(
        {"id": "y", "category": "c", "query": "q", "grading": "structural", "expects_error": True}, pipeline=broken
    )

    assert execution["soft_f1"] == 0.0
    assert reject["soft_f1"] is None


# --- latency warm-up ---

def test_summarize_excludes_first_latency_as_warmup():
    records = [_record("a", True, latency=9000), _record("a", True, latency=100), _record("a", True, latency=200)]

    latency = run_eval.summarize(records)["latency_ms"]

    assert latency["p50"] == 100
    assert latency["p95"] == 200
    assert latency["warmup_excluded_ms"] == 9000


# --- config ---

def test_collect_config_records_reproducibility_fields(monkeypatch, tmp_path):
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps([{"id": "a"}, {"id": "b"}]), encoding="utf-8")
    monkeypatch.setenv("VECTOR_CACHE_ENABLED", "0")
    monkeypatch.setenv("VECTOR_CACHE_THRESHOLD", "0.9")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")

    config = run_eval.collect_config("v1", False, filter_value="course", golden_path=golden, hints_used=False)

    assert config["filter"] == "course"
    assert config["hints_used"] is False
    assert config["golden"] == {
        "sha256": hashlib.sha256(golden.read_bytes()).hexdigest(),
        "case_count": 2,
    }
    assert config["env"]["VECTOR_CACHE_ENABLED"] == "0"
    assert config["env"]["VECTOR_CACHE_THRESHOLD"] == "0.9"
    assert config["env"]["OLLAMA_BASE_URL"] == "http://ollama:11434"
    assert "git_sha" in config


def test_collect_config_git_sha_is_none_when_git_is_unavailable(monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(run_eval.subprocess, "run", no_git)

    assert run_eval.collect_config("v1", False)["git_sha"] is None


def test_main_rejects_decoupled_with_pipeline_that_ignores_hints(monkeypatch, tmp_path, capsys):
    _write_cases(tmp_path, monkeypatch)

    def must_not_run(query, **kwargs):
        raise AssertionError("must not run")

    must_not_run.accepts_value_hints = False
    monkeypatch.setitem(run_eval.PIPELINES, "v1", must_not_run)

    assert run_eval.main(["--decoupled", "--report-dir", str(tmp_path / "reports")]) == 2
    assert "value_hints" in capsys.readouterr().out


def test_main_writes_hints_used_into_report_config(monkeypatch, tmp_path):
    monkeypatch.setenv("VECTOR_CACHE_ENABLED", "1")
    _write_cases(tmp_path, monkeypatch)

    def hinted(query, **kwargs):
        return {"sql": "SELECT 1", "data": []}

    hinted.accepts_value_hints = True
    monkeypatch.setitem(run_eval.PIPELINES, "v1", hinted)

    run_eval.main(["--decoupled", "--filter", "c", "--report-dir", str(tmp_path / "reports")])

    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text(encoding="utf-8"))
    assert report["config"]["hints_used"] is True
    assert report["config"]["filter"] == "c"
    assert report["config"]["env"]["VECTOR_CACHE_ENABLED"] == "0"
