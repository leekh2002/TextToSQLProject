"""v2 pipeline: values -> examples -> N candidates -> execute -> vote -> retry (spec 3)."""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable

from .config import MISSING_MODEL_ERROR, Settings
from .examples import REVIEW_LOG_PATH, is_personal_example
from .execute import CandidateOutcome, run_candidate
from .generate import generate_with_errors
from .prompt import build_messages
from .values import find_value_candidates, from_hints
from .vote import decide

REJECTED_ERROR = "질문이 모호합니다."
NO_SQL_ERROR = "SQL을 생성하지 못했습니다."
LLM_ERROR_PREFIX = "LLM 호출 실패: "


@dataclass
class Deps:
    preprocess: Callable
    references: dict
    store: object
    schema: str
    chat: Callable
    run: Callable
    validate: Callable
    expand: Callable | None
    exclude: Callable | None
    settings: Settings


@lru_cache(maxsize=1)
def _default_references() -> dict:
    from .. import db
    from .values import load_value_references

    return load_value_references(db.run_query)


def _build_store(settings: Settings):
    if not settings.use_examples:
        return None
    from .examples import default_store

    return default_store()


def default_deps() -> Deps:
    from ..keyword_extract import preprocess_query
    from ..validate import validate_generated_sql
    from .config import load_settings
    from .execute import run_sql
    from .generate import ollama_chat
    from .schema_doc import get_mschema

    settings = load_settings()
    return Deps(
        preprocess=lambda q: preprocess_query(q, fail_open=True),
        references=_default_references(),
        store=_build_store(settings),
        schema=get_mschema(),
        chat=ollama_chat,
        run=run_sql,
        validate=validate_generated_sql,
        expand=None,
        exclude=None,
        settings=settings,
    )


def _write_review_log(query, outcome: CandidateOutcome | None, error) -> None:
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "sql": outcome.extracted_sql if outcome else None,
            "rows": len(outcome.rows) if outcome and outcome.rows is not None else None,
            "error": error,
        }
        REVIEW_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REVIEW_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def run_v2(query, *, exclude_completed_courses=False, student_id=None, value_hints=None, deps=None) -> dict:
    started = time.perf_counter()
    deps = deps or default_deps()
    settings = deps.settings
    if not (settings.model or "").strip():
        raise RuntimeError(MISSING_MODEL_ERROR)

    t0 = time.perf_counter()
    preprocessing = deps.preprocess(query) or {}
    entities = preprocessing.get("corrected_entities") or []
    preprocess_ms = (time.perf_counter() - t0) * 1000

    if value_hints is not None:
        values = from_hints(value_hints)
    else:
        values = find_value_candidates(query, entities, deps.references, settings.value_sources)

    examples = []
    if settings.use_examples:
        k = settings.examples_k
        if student_id is None:
            found = [example for example, _ in deps.store.search(query, 3 * k)]
            examples = [e for e in found if not is_personal_example(e)][:k]
        else:
            examples = [example for example, _ in deps.store.search(query, k)]

    def messages_for(order):
        return build_messages(query, schema=deps.schema, hints=values, examples=order,
                              logged_in=student_id is not None, exclude_completed=exclude_completed_courses)

    sets = []
    for i in range(settings.candidates):
        order = list(examples)
        if i > 0:
            random.Random(i).shuffle(order)
        sets.append(messages_for(order))

    t0 = time.perf_counter()
    generated = generate_with_errors(sets, model=settings.model, temperature=settings.temperature, chat=deps.chat,
                                     stop=settings.stop, max_tokens=settings.max_tokens)
    raws = [text for text, _ in generated]
    llm_errors = [err for _, err in generated]
    llm_ms = (time.perf_counter() - t0) * 1000

    def execute(index, raw):
        return run_candidate(index, raw, student_id=student_id, exclude_completed=exclude_completed_courses,
                             settings=settings, run=deps.run, validate=deps.validate,
                             expand=deps.expand, exclude=deps.exclude)

    t0 = time.perf_counter()
    outcomes = [execute(i, raw) for i, raw in enumerate(raws)]
    decision = decide(outcomes, len(raws))
    execute_ms = (time.perf_counter() - t0) * 1000

    if decision.kind in ("none", "empty") and sets:
        first = outcomes[0]
        if first.rejected or first.sql is None:
            note = "위 답변은 실행할 SQL이 아니었다. 질문에 맞는 SQL을 작성해서 SQL만 출력해."
        elif first.error:
            note = f"위 SQL은 실행 결과가 오류: {first.error}였다. 질문 의도에 맞게 고친 SQL만 출력해."
        else:
            note = "위 SQL은 실행 결과가 0행이었다. 질문 의도에 맞게 고친 SQL만 출력해."
        retry_messages = sets[0] + [
            {"role": "assistant", "content": raws[0] or ""},
            {"role": "user", "content": note},
        ]
        t0 = time.perf_counter()
        try:
            retry_raw = deps.chat(retry_messages, model=settings.model, temperature=0.0,
                                  stop=settings.stop, max_tokens=settings.max_tokens)
        except Exception as exc:
            retry_raw = None
            llm_errors.append(str(exc) or type(exc).__name__)
        llm_ms += (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        retry_outcome = execute(len(outcomes), retry_raw)
        execute_ms += (time.perf_counter() - t0) * 1000
        outcomes.append(retry_outcome)
        if retry_outcome.rows:
            decision = type(decision)("answer", retry_outcome.index)

    chosen = outcomes[decision.index] if decision.index is not None else None
    if decision.kind == "rejected":
        sql, data, error, rejected = None, [], REJECTED_ERROR, True
    elif decision.kind == "none" and all(llm_errors) and len(llm_errors) > len(raws):
        sql, data, error, rejected = None, [], LLM_ERROR_PREFIX + llm_errors[0], False
    elif decision.kind == "none":
        errors = [o.error for o in outcomes if o.error]
        last_sql = next((o.sql for o in reversed(outcomes) if o.sql), None)
        sql, data, error, rejected = last_sql, [], (errors[0] if errors else NO_SQL_ERROR), False
    else:
        sql, data, error, rejected = chosen.executed_sql, chosen.rows, None, False

    if settings.review_log and not rejected:
        log_outcome = chosen or next((o for o in reversed(outcomes) if o.sql), None)
        _write_review_log(query, log_outcome, error)

    return {
        "sql": sql,
        "data": data,
        "error": error,
        "rejected": rejected,
        "cache_hit": False,
        "query": query,
        "candidates": [
            {"index": o.index, "sql": o.sql, "rows": None if o.rows is None else len(o.rows),
             "error": o.error, "rejected": o.rejected}
            for o in outcomes
        ],
        "timings_ms": {
            "preprocess_ms": round(preprocess_ms, 1),
            "llm_ms": round(llm_ms, 1),
            "execute_ms": round(execute_ms, 1),
            "total_ms": round((time.perf_counter() - started) * 1000, 1),
        },
        "value_candidates": [{"column": v.column, "value": v.value, "source": v.source} for v in values],
    }


run_v2.accepts_value_hints = True
