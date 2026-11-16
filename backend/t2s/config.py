"""v2 pipeline settings, read from the environment at call time (eval ablations flip them)."""
from __future__ import annotations

import os
from dataclasses import dataclass


MISSING_MODEL_ERROR = "LLM 모델이 설정되지 않았습니다. T2S_MODEL 또는 OLLAMA_MODEL을 지정하세요."


@dataclass(frozen=True)
class Settings:
    model: str
    candidates: int
    temperature: float
    examples_k: int
    use_examples: bool
    value_sources: tuple[str, ...]
    row_cap: int
    statement_timeout_ms: int
    review_log: bool
    stop: tuple[str, ...]
    max_tokens: int


DEFAULT_STOP = ("###", "Below is an instruction", "\n\n\n")


def _stop_sequences() -> tuple[str, ...]:
    raw = os.getenv("T2S_STOP")
    if raw is None:
        return DEFAULT_STOP
    return tuple(part for part in raw.split("||") if part)


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", ""}


def load_settings() -> Settings:
    sources = os.getenv("T2S_VALUE_SOURCES", "ner,ngram")
    model = os.getenv("T2S_MODEL") or os.getenv("OLLAMA_MODEL", "")
    if not model.strip():
        raise RuntimeError(MISSING_MODEL_ERROR)
    return Settings(
        model=model,
        candidates=int(os.getenv("T2S_CANDIDATES", "1")),
        temperature=float(os.getenv("T2S_TEMPERATURE", "0.4")),
        examples_k=int(os.getenv("T2S_EXAMPLES_K", "4")),
        use_examples=_flag("T2S_USE_EXAMPLES", "1"),
        value_sources=tuple(s.strip() for s in sources.split(",") if s.strip()),
        row_cap=int(os.getenv("T2S_ROW_CAP", "50")),
        statement_timeout_ms=int(os.getenv("T2S_STATEMENT_TIMEOUT_MS", "3000")),
        review_log=_flag("T2S_REVIEW_LOG", "1"),
        stop=_stop_sequences(),
        max_tokens=int(os.getenv("T2S_MAX_TOKENS", "256")),
    )
