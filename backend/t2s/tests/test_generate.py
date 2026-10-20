import pytest

from backend.t2s.generate import extract_sql, generate_candidates, generate_with_errors


@pytest.mark.parametrize("text, expected", [
    ("SELECT 1 FROM v_course_info;", "SELECT 1 FROM v_course_info"),
    ("```sql\nSELECT a\nFROM t\n```", "SELECT a\nFROM t"),
    ("답: select a from t; 추가 설명", "select a from t"),
    ("UNKNOWN", "UNKNOWN"),
    ("unknown.", "UNKNOWN"),
    ("WITH x AS (SELECT 1) SELECT * FROM x", "WITH x AS (SELECT 1) SELECT * FROM x"),
    ("모르겠어요", None),
    (None, None),
])
def test_extract_sql(text, expected):
    assert extract_sql(text) == expected


def test_generate_candidates_uses_greedy_first_and_keeps_order():
    calls = []

    def chat(messages, *, model, temperature, seed=None):
        calls.append((messages[0]["content"], temperature, seed))
        if messages[0]["content"] == "boom":
            raise RuntimeError("down")
        return f"SELECT {messages[0]['content']}"

    sets = [[{"role": "user", "content": c}] for c in ("a", "boom", "c")]

    out = generate_candidates(sets, model="m", temperature=0.7, chat=chat)

    assert out == ["SELECT a", None, "SELECT c"]
    assert sorted(calls) == sorted([("a", 0.0, None), ("boom", 0.7, 1), ("c", 0.7, 2)])


def test_generate_with_errors_keeps_exception_text():
    def chat(messages, *, model, temperature, seed=None):
        if seed == 1:
            raise RuntimeError("model not found")
        return "SELECT 1"

    sets = [[{"role": "user", "content": "x"}]] * 2

    assert generate_with_errors(sets, model="m", temperature=0.7, chat=chat) == [("SELECT 1", None), (None, "model not found")]
