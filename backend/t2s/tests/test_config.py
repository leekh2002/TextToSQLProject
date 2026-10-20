from backend.t2s.config import load_settings


def test_defaults(monkeypatch):
    for key in ("T2S_MODEL", "T2S_CANDIDATES", "T2S_TEMPERATURE", "T2S_EXAMPLES_K", "T2S_USE_EXAMPLES",
                "T2S_VALUE_SOURCES", "T2S_ROW_CAP", "T2S_STATEMENT_TIMEOUT_MS", "T2S_REVIEW_LOG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "base-m")

    s = load_settings()

    assert (s.model, s.candidates, s.temperature, s.examples_k) == ("base-m", 5, 0.7, 4)
    assert s.use_examples is True and s.review_log is True
    assert s.value_sources == ("ner", "ngram")
    assert (s.row_cap, s.statement_timeout_ms) == (50, 3000)


def test_overrides(monkeypatch):
    monkeypatch.setenv("T2S_MODEL", "x")
    monkeypatch.setenv("T2S_CANDIDATES", "1")
    monkeypatch.setenv("T2S_USE_EXAMPLES", "0")
    monkeypatch.setenv("T2S_VALUE_SOURCES", "ngram")
    monkeypatch.setenv("T2S_REVIEW_LOG", "0")

    s = load_settings()

    assert (s.model, s.candidates, s.use_examples, s.value_sources, s.review_log) == ("x", 1, False, ("ngram",), False)
