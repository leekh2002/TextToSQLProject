from backend.t2s.config import Settings
from backend.t2s.execute import bind_student, run_candidate

SETTINGS = Settings(model="m", candidates=5, temperature=0.7, examples_k=4, use_examples=True,
                    value_sources=("ner", "ngram"), row_cap=50, statement_timeout_ms=3000, review_log=False,
                    stop=("###",), max_tokens=256)


def ok_validate(sql, requested_student_id=None):
    return {"ok": True, "reason": None}


def test_bind_student_escapes_other_percents():
    sql, params = bind_student("SELECT 1 FROM e WHERE e.student_id = %(student_id)s AND x LIKE '%a%'", "202102671")

    assert sql == "SELECT 1 FROM e WHERE e.student_id = %(student_id)s AND x LIKE '%%a%%'"
    assert params == {"student_id": "202102671"}
    assert bind_student("SELECT '%a%'", None) == ("SELECT '%a%'", None)


def test_unknown_is_rejected_without_running():
    outcome = run_candidate(0, "UNKNOWN", student_id=None, exclude_completed=False, settings=SETTINGS,
                            run=lambda *a: (_ for _ in ()).throw(AssertionError()), validate=ok_validate)

    assert outcome.rejected and outcome.rows is None


def test_course_row_query_is_normalized_limited_expanded_and_run():
    seen = {}

    def run(sql, params, timeout_ms):
        seen["sql"], seen["params"], seen["timeout"] = sql, params, timeout_ms
        return [{"subject_code": "A"}]

    outcome = run_candidate(
        1, "SELECT subject_name FROM v_course_info WHERE day_of_week = '목'",
        student_id=None, exclude_completed=False, settings=SETTINGS, run=run, validate=ok_validate,
        expand=lambda sql: sql + " /*x*/", exclude=lambda sql, sid: sql,
    )

    assert outcome.rows == [{"subject_code": "A"}] and outcome.error is None
    assert "v_course_info.course_year" in outcome.sql and outcome.sql.endswith("LIMIT 50")
    assert seen["sql"].endswith("/*x*/") and seen["params"] is None and seen["timeout"] == 3000


def test_validation_safety_failure_is_a_rejection_other_failure_is_an_error():
    def deny(reason):
        return lambda sql, requested_student_id=None: {"ok": False, "reason": reason}

    kwargs = dict(student_id=None, exclude_completed=False, settings=SETTINGS, run=lambda *a: [])

    assert run_candidate(0, "SELECT 1 FROM v_course_info", validate=deny("SELECT 문만 허용됩니다."), **kwargs).rejected
    other = run_candidate(0, "SELECT 1 FROM v_course_info", validate=deny("기본 LIMIT가 필요합니다."), **kwargs)
    assert not other.rejected and other.error == "기본 LIMIT가 필요합니다."


def test_with_candidate_is_a_format_miss_not_a_rejection():
    def deny_select_only(sql, requested_student_id=None):
        return {"ok": False, "reason": "SELECT 문만 허용됩니다."}

    outcome = run_candidate(0, "WITH x AS (SELECT 1) SELECT * FROM x", student_id=None, exclude_completed=False,
                            settings=SETTINGS, run=lambda *a: [], validate=deny_select_only)

    assert not outcome.rejected
    assert outcome.error == "WITH 문은 지원하지 않습니다."
    assert outcome.rows is None


def test_exclusion_and_binding_for_student_queries():
    seen = {}

    def run(sql, params, timeout_ms):
        seen["sql"], seen["params"] = sql, params
        return []

    run_candidate(
        0, "SELECT COUNT(*) FROM v_course_info", student_id="202102671", exclude_completed=True,
        settings=SETTINGS, run=run, validate=ok_validate,
        expand=lambda sql: sql, exclude=lambda sql, sid: f"{sql} /*ex {sid}*/",
    )

    assert seen["sql"].endswith("/*ex 202102671*/") and seen["params"] is None


def test_runtime_error_is_recorded():
    def run(sql, params, timeout_ms):
        raise RuntimeError("canceling statement due to statement timeout")

    outcome = run_candidate(0, "SELECT 1 FROM v_course_info", student_id=None, exclude_completed=False,
                            settings=SETTINGS, run=run, validate=ok_validate, expand=lambda s: s, exclude=lambda s, i: s)

    assert outcome.rows is None and "timeout" in outcome.error


def test_rewrite_failure_is_recorded_as_error():
    def exclude(sql, sid):
        raise Exception("v_course_info is required to exclude completed courses")

    outcome = run_candidate(0, "SELECT COUNT(*) FROM e", student_id="202102671", exclude_completed=True,
                            settings=SETTINGS, run=lambda *a: [], validate=ok_validate,
                            expand=lambda s: s, exclude=exclude)

    assert outcome.rows is None and not outcome.rejected
    assert outcome.error == "v_course_info is required to exclude completed courses"


def test_anonymous_personal_queries_are_rejected_without_running():
    def boom(*a):
        raise AssertionError("must not run")

    for sql in (
        "SELECT * FROM enrollment WHERE student_id = %(student_id)s",
        "SELECT COUNT(*) FROM enrollment",
        "SELECT name FROM student",
    ):
        outcome = run_candidate(0, sql, student_id=None, exclude_completed=False, settings=SETTINGS,
                                run=boom, validate=ok_validate)
        assert outcome.rejected and outcome.rows is None and outcome.error is None


def test_real_validator_anonymous_enrollment_rejected_logged_in_runs():
    from backend.validate import validate_generated_sql

    sql = "SELECT subject_code FROM enrollment WHERE student_id = %(student_id)s"
    boom = lambda *a: (_ for _ in ()).throw(AssertionError("must not run"))

    anonymous = run_candidate(0, sql, student_id=None, exclude_completed=False, settings=SETTINGS,
                              run=boom, validate=validate_generated_sql)
    assert anonymous.rejected and anonymous.rows is None

    seen = {}

    def run(bound, params, timeout_ms):
        seen["params"] = params
        return [{"subject_code": "A"}]

    member = run_candidate(0, sql, student_id="202102671", exclude_completed=False, settings=SETTINGS,
                           run=run, validate=validate_generated_sql)
    assert member.rows == [{"subject_code": "A"}] and not member.rejected
    assert seen["params"] == {"student_id": "202102671"}


def test_extracted_sql_is_kept_before_normalization():
    outcome = run_candidate(0, "SELECT subject_name FROM v_course_info", student_id=None, exclude_completed=False,
                            settings=SETTINGS, run=lambda *a: [], validate=ok_validate, expand=lambda s: s)

    assert outcome.extracted_sql == "SELECT subject_name FROM v_course_info"
    assert "course_year" in outcome.sql


def test_top_n_course_rows_use_key_preserving_expansion():
    seen = {}

    def run(sql, params, timeout_ms):
        seen["sql"] = sql
        return [{"subject_code": "A"}]

    def process_expand(sql):
        raise AssertionError("process expansion drops ORDER BY/LIMIT")

    run_candidate(
        0, "SELECT * FROM v_course_info WHERE start_time < '12:00:00' ORDER BY capacity DESC LIMIT 1",
        student_id=None, exclude_completed=False, settings=SETTINGS, run=run, validate=ok_validate,
        expand=process_expand, exclude=lambda s, i: s,
    )

    assert "SELECT DISTINCT sub.subject_code, sub.section FROM (" in seen["sql"]
    assert "ORDER BY capacity DESC LIMIT 1" in seen["sql"]


def test_limit_at_or_above_cap_or_without_order_keeps_process_expansion():
    seen = []
    for sql in (
        "SELECT * FROM v_course_info WHERE day_of_week = '월' ORDER BY capacity DESC LIMIT 50",
        "SELECT * FROM v_course_info WHERE day_of_week = '월' LIMIT 3",
        "SELECT * FROM v_course_info WHERE day_of_week = '월' ORDER BY capacity DESC",
    ):
        run_candidate(0, sql, student_id=None, exclude_completed=False, settings=SETTINGS,
                      run=lambda *a: [], validate=ok_validate, expand=lambda s: seen.append(s) or s,
                      exclude=lambda s, i: s)

    assert len(seen) == 3


def test_run_sql_session_is_read_only(monkeypatch):
    from backend.t2s import execute

    captured = {}

    class Conn:
        def cursor(self):
            raise RuntimeError("stop")

        def close(self):
            pass

    def connect(dsn, **kwargs):
        captured.update(kwargs)
        return Conn()

    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(execute.psycopg2, "connect", connect)

    try:
        execute.run_sql("SELECT 1", None, 1234)
    except RuntimeError:
        pass

    assert "-c default_transaction_read_only=on" in captured["options"]
    assert "-c statement_timeout=1234" in captured["options"]
