from backend.t2s.config import Settings
from backend.t2s.execute import bind_student, run_candidate

SETTINGS = Settings("m", 5, 0.7, 4, True, ("ner", "ngram"), 50, 3000, False)


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
