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
    ("SELECT * FROM v_course_info WHERE start_time >= '12:00:00'Below is an instruction that describes a task, ...\r\n\r\n### Instruction:\r\nfoo",
     "SELECT * FROM v_course_info WHERE start_time >= '12:00:00'"),
    ("SELECT a FROM t WHERE x = 1\r\n\r\n### Instruction:\r\nshow all", "SELECT a FROM t WHERE x = 1"),
    ("select a from t\n### Response: junk", "select a from t"),
    ("SELECT 1 BELOW IS AN INSTRUCTION trailing", "SELECT 1"),
])
def test_extract_sql(text, expected):
    assert extract_sql(text) == expected


def test_ollama_chat_sends_stop_and_num_predict(monkeypatch):
    import io
    import json

    from backend.t2s import generate

    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["payload"] = json.loads(req.data.decode("utf-8"))
        return io.BytesIO(json.dumps({"message": {"content": "SELECT 1"}}).encode("utf-8"))

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local")
    monkeypatch.setattr(generate.request, "urlopen", fake_urlopen)

    out = generate.ollama_chat([{"role": "user", "content": "q"}], model="m", temperature=0.0,
                               stop=("###", "\n\n\n"), max_tokens=64)

    assert out == "SELECT 1"
    assert sent["payload"]["options"]["stop"] == ["###", "\n\n\n"]
    assert sent["payload"]["options"]["num_predict"] == 64


def test_generate_with_errors_passes_stop_and_max_tokens():
    seen = []

    def chat(messages, *, model, temperature, seed=None, stop=None, max_tokens=None):
        seen.append((stop, max_tokens))
        return "SELECT 1"

    generate_with_errors([[{"role": "user", "content": "x"}]], model="m", temperature=0.0, chat=chat,
                         stop=("###",), max_tokens=99)

    assert seen == [(("###",), 99)]


def test_generate_candidates_uses_greedy_first_and_keeps_order():
    calls = []

    def chat(messages, *, model, temperature, seed=None, **_):
        calls.append((messages[0]["content"], temperature, seed))
        if messages[0]["content"] == "boom":
            raise RuntimeError("down")
        return f"SELECT {messages[0]['content']}"

    sets = [[{"role": "user", "content": c}] for c in ("a", "boom", "c")]

    out = generate_candidates(sets, model="m", temperature=0.7, chat=chat)

    assert out == ["SELECT a", None, "SELECT c"]
    assert sorted(calls) == sorted([("a", 0.0, None), ("boom", 0.7, 1), ("c", 0.7, 2)])


def test_generate_with_errors_keeps_exception_text():
    def chat(messages, *, model, temperature, seed=None, **_):
        if seed == 1:
            raise RuntimeError("model not found")
        return "SELECT 1"

    sets = [[{"role": "user", "content": "x"}]] * 2

    assert generate_with_errors(sets, model="m", temperature=0.7, chat=chat) == [("SELECT 1", None), (None, "model not found")]
