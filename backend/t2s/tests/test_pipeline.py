import json

import numpy as np

from backend.t2s import pipeline as pipeline_module
from backend.t2s.config import Settings
from backend.t2s.examples import Example, ExampleStore
from backend.t2s.pipeline import Deps, run_v2


def settings(**kw):
    base = dict(model="m", candidates=3, temperature=0.7, examples_k=1, use_examples=True,
                value_sources=("ngram",), row_cap=50, statement_timeout_ms=3000, review_log=False,
                stop=("###",), max_tokens=256)
    base.update(kw)
    return Settings(**base)


def deps(chat, run, **kw):
    store = ExampleStore([Example("e1", "예시", "SELECT 1")], lambda t: np.array([1.0], dtype=np.float32))
    return Deps(
        preprocess=lambda q: {"corrected_entities": []},
        references={"dept_name": ["공과대학 컴퓨터융합학부"]},
        store=store, schema="# Table: v_course_info", chat=chat, run=run,
        validate=lambda sql, requested_student_id=None: {"ok": True, "reason": None},
        expand=lambda sql: sql, exclude=lambda sql, sid: sql, settings=kw.get("settings", settings()),
    )


def test_majority_answer_and_response_shape():
    answers = iter(["SELECT COUNT(*) FROM v_course_info", "SELECT a FROM v_course_info", "SELECT COUNT(*) FROM v_course_info"])
    seen = []

    def chat(messages, *, model, temperature, seed=None, **_):
        seen.append(messages)
        return next(answers)

    def run(sql, params, timeout_ms):
        return [{"n": 1}] if "COUNT" in sql else [{"n": 2}]

    result = run_v2("컴퓨터융합학부 과목 수", deps=deps(chat, run))

    assert result["data"] == [{"n": 1}] and result["error"] is None and result["rejected"] is False
    assert len(result["candidates"]) == 3 and result["cache_hit"] is False
    assert result["value_candidates"] == [{"column": "dept_name", "value": "공과대학 컴퓨터융합학부", "source": "ngram"}]
    assert any(m["content"] == "질문: 예시" for m in seen[0])


def test_hints_replace_value_search():
    captured = []

    def chat(messages, *, model, temperature, seed=None, **_):
        captured.append(messages[-1]["content"])
        return "UNKNOWN"

    result = run_v2("q", value_hints=[{"column": "category", "value": "전공(핵심)"}], deps=deps(chat, lambda *a: []))

    assert "category = '전공(핵심)'" in captured[0] and "dept_name" not in captured[0]
    assert result["rejected"] is True and result["error"] == "질문이 모호합니다."


def test_retry_when_all_candidates_empty():
    replies = iter(["SELECT a FROM v_course_info"] * 3 + ["SELECT b FROM v_course_info"])

    def chat(messages, *, model, temperature, seed=None, **_):
        return next(replies)

    result = run_v2("q", deps=deps(chat, lambda sql, p, t: []))

    assert len(result["candidates"]) == 4
    assert result["data"] == [] and result["error"] is None


def test_errors_everywhere_return_error_response():
    def chat(messages, *, model, temperature, seed=None, **_):
        raise RuntimeError("down")

    result = run_v2("q", deps=deps(chat, lambda *a: []))

    assert result["data"] == [] and result["error"] and result["rejected"] is False


def test_retry_recovers_with_non_empty_result():
    calls = []

    def chat(messages, *, model, temperature, seed=None, **_):
        calls.append(messages)
        return "SELECT a FROM v_course_info" if len(calls) <= 3 else "SELECT b FROM v_course_info"

    runs = []

    def run(sql, params, timeout_ms):
        runs.append(sql)
        return [{"b": 1}] if len(runs) > 3 else []

    result = run_v2("q", deps=deps(chat, run))

    retry = max(calls, key=len)
    assert retry[-2]["role"] == "assistant" and "0행" in retry[-1]["content"]
    assert result["data"] == [{"b": 1}] and len(result["candidates"]) == 4


def test_review_log_record_keys(tmp_path, monkeypatch):
    log = tmp_path / "logs" / "review.jsonl"
    monkeypatch.setattr(pipeline_module, "REVIEW_LOG_PATH", log)

    def chat(messages, *, model, temperature, seed=None, **_):
        return "SELECT 1 FROM v_course_info"

    run_v2("질문", deps=deps(chat, lambda *a: [{"n": 1}], settings=settings(review_log=True)))

    record = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert set(record) == {"ts", "query", "sql", "rows", "error"}
    assert record["sql"] == "SELECT 1 FROM v_course_info"
    assert record["query"] == "질문" and record["rows"] == 1 and record["error"] is None


def test_all_llm_calls_failing_reports_llm_error():
    def chat(messages, *, model, temperature, seed=None, **_):
        raise RuntimeError("connection refused")

    result = run_v2("q", deps=deps(chat, lambda *a: []))

    assert result["error"] == "LLM 호출 실패: connection refused"
    assert result["rejected"] is False and result["data"] == []


def test_partial_llm_failure_is_not_an_llm_error():
    def chat(messages, *, model, temperature, seed=None, **_):
        if seed == 1:
            raise RuntimeError("down")
        return "UNKNOWN"

    result = run_v2("q", deps=deps(chat, lambda *a: []))

    assert result["rejected"] is True


def test_empty_model_fails_fast():
    import pytest

    with pytest.raises(RuntimeError, match="모델"):
        run_v2("q", deps=deps(lambda *a, **k: "UNKNOWN", lambda *a: [], settings=settings(model="")))


def _retry_feedback(first_reply, run):
    calls = []

    def chat(messages, *, model, temperature, seed=None, **_):
        calls.append(messages)
        is_retry = messages[-1]["content"].startswith("위 ")
        is_first_candidate = seed is None and not is_retry
        return first_reply if is_first_candidate else "SELECT a FROM v_course_info"

    run_v2("q", deps=deps(chat, run))
    return max(calls, key=len)[-1]["content"]


def test_retry_feedback_depends_on_first_candidate_state():
    def failing_run(sql, params, timeout_ms):
        raise RuntimeError("boom")

    assert "오류: boom" in _retry_feedback("SELECT a FROM v_course_info", failing_run)
    assert "0행" in _retry_feedback("SELECT a FROM v_course_info", lambda *a: [])
    for reply in ("모르겠어요", "UNKNOWN"):
        feedback = _retry_feedback(reply, lambda *a: [])
        assert "0행" not in feedback and "오류" not in feedback and "SQL" in feedback


def test_store_not_built_when_examples_disabled(monkeypatch):
    from backend.t2s import examples

    monkeypatch.setattr(examples, "default_store", lambda: (_ for _ in ()).throw(AssertionError("built")))

    assert pipeline_module._build_store(settings(use_examples=False)) is None


def test_stop_and_max_tokens_reach_every_call_including_retry():
    seen = []

    def chat(messages, *, model, temperature, seed=None, stop=None, max_tokens=None):
        seen.append((stop, max_tokens))
        return "SELECT a FROM v_course_info"

    run_v2("q", deps=deps(chat, lambda *a: [], settings=settings(stop=("###",), max_tokens=77)))

    assert len(seen) == 4
    assert all(call == (("###",), 77) for call in seen)


def _personal_store():
    vectors = {"질문": 1.0, "개인1": 0.9, "개인2": 0.8, "공개1": 0.7, "공개2": 0.6}
    examples = [
        Example("p1", "개인1", "SELECT * FROM enrollment"),
        Example("p2", "개인2", "SELECT * FROM v_course_info WHERE s = %(student_id)s"),
        Example("o1", "공개1", "SELECT 1 FROM v_course_info"),
        Example("o2", "공개2", "SELECT a FROM v_course_info"),
    ]
    return ExampleStore(examples, lambda t: np.array([vectors.get(t, 0.0), 1.0], dtype=np.float32))


def _example_questions(student_id):
    seen = []

    def chat(messages, *, model, temperature, seed=None, **_):
        seen.append(messages)
        return "SELECT 1 FROM v_course_info"

    d = deps(chat, lambda sql, params, timeout_ms: [{"n": 1}], settings=settings(examples_k=2, candidates=1))
    d.store = _personal_store()
    run_v2("질문", student_id=student_id, deps=d)
    return [m["content"] for m in seen[0] if m["role"] == "user"][:-1]


def test_anonymous_users_get_the_same_examples_as_logged_in_users():
    assert _example_questions(None) == ["질문: 개인1", "질문: 개인2"]


def test_logged_in_users_keep_personal_examples():
    assert _example_questions("20240001") == ["질문: 개인1", "질문: 개인2"]


def test_single_candidate_answers_without_retry():
    calls = []

    def chat(messages, *, model, temperature, seed=None, **_):
        calls.append(messages)
        return "SELECT a FROM v_course_info"

    result = run_v2("q", deps=deps(chat, lambda sql, p, t: [{"a": 1}], settings=settings(candidates=1)))

    assert len(calls) == 1 and len(result["candidates"]) == 1
    assert result["data"] == [{"a": 1}] and result["error"] is None


def test_single_candidate_retries_when_empty():
    replies = iter(["SELECT a FROM v_course_info", "SELECT b FROM v_course_info"])
    runs = []

    def chat(messages, *, model, temperature, seed=None, **_):
        return next(replies)

    def run(sql, p, t):
        runs.append(sql)
        return [] if len(runs) == 1 else [{"b": 1}]

    result = run_v2("q", deps=deps(chat, run, settings=settings(candidates=1)))

    assert len(result["candidates"]) == 2 and result["data"] == [{"b": 1}]
