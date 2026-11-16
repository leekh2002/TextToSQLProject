import pytest
from fastapi import HTTPException

from backend import main
from backend.t2s import pipeline


def _req(exclude=False):
    return main.QueryRequest(query="q", excludeCompletedCourses=exclude)


@pytest.fixture
def calls(monkeypatch):
    calls = {"process": [], "v2": [], "auth": 0}
    monkeypatch.setattr(main, "process", lambda q, **kw: calls["process"].append(kw) or {"v": 1})
    monkeypatch.setattr(pipeline, "run_v2", lambda q, **kw: calls["v2"].append(kw) or {"v": 2})

    def auth(header):
        calls["auth"] += 1
        return {"studentNo": "S1"}

    monkeypatch.setattr(main, "_student_from_authorization", auth)
    return calls


def test_v1_default_unchanged(calls, monkeypatch):
    monkeypatch.delenv("T2S_PIPELINE", raising=False)
    assert main._run_query(_req(), "Bearer x") == {"v": 1}
    assert calls["auth"] == 0 and calls["process"][0]["student_id"] is None
    main._run_query(_req(True), "Bearer x")
    assert calls["process"][1]["student_id"] == "S1" and not calls["v2"]


def test_v2_valid_header_passes_student(calls, monkeypatch):
    monkeypatch.setenv("T2S_PIPELINE", "v2")
    assert main._run_query(_req(), "Bearer x") == {"v": 2}
    assert calls["v2"][0] == {"exclude_completed_courses": False, "student_id": "S1"}


def test_v2_no_header_is_anonymous(calls, monkeypatch):
    monkeypatch.setenv("T2S_PIPELINE", "v2")
    main._run_query(_req(), None)
    assert calls["v2"][0]["student_id"] is None and calls["auth"] == 0


@pytest.mark.parametrize("exc", [HTTPException(status_code=401, detail="bad"), RuntimeError("db")])
def test_v2_bad_token_falls_back_to_anonymous(calls, monkeypatch, exc):
    monkeypatch.setenv("T2S_PIPELINE", "v2")

    def boom(header):
        raise exc

    monkeypatch.setattr(main, "_student_from_authorization", boom)
    assert main._run_query(_req(), "Bearer stale") == {"v": 2}
    assert calls["v2"][0]["student_id"] is None


def test_v2_exclude_with_failing_auth_propagates(calls, monkeypatch):
    monkeypatch.setenv("T2S_PIPELINE", "v2")

    def boom(header):
        raise HTTPException(status_code=401, detail="bad")

    monkeypatch.setattr(main, "_student_from_authorization", boom)
    with pytest.raises(HTTPException) as info:
        main._run_query(_req(True), "Bearer stale")
    assert info.value.status_code == 401 and not calls["v2"]
