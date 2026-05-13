import time

from .db import run_query
from .keyword_extract import preprocess_query
from .llm import fix_sql, generate_sql
from .redis_cache import get_cache, set_cache
from .utils import log_query
from .validate import validate_generated_sql


def enforce_limit(sql):
    if "limit" not in sql.lower():
        sql += " LIMIT 50"
    return sql


def validate_sql(sql, requested_student_id=None):
    result = validate_generated_sql(sql, requested_student_id=requested_student_id)
    if not result["ok"]:
        raise Exception(result["reason"] or "SQL validation failed")
    return True


def _with_query_context(response, query, normalized_query, preprocessing):
    response["query"] = query
    response["normalized_query"] = normalized_query
    response["preprocessing"] = preprocessing
    return response


def process(query):
    started_total = time.perf_counter()
    timings = {
        "cache_lookup_ms": 0,
        "preprocess_ms": 0,
        "llm_ms": 0,
        "validate_ms": 0,
        "db_ms": 0,
        "total_ms": 0,
    }

    t_pre = time.perf_counter()
    preprocessing = preprocess_query(query)
    normalized_query = preprocessing["corrected_query"]
    timings["preprocess_ms"] = int((time.perf_counter() - t_pre) * 1000)

    t0 = time.perf_counter()
    cached = get_cache(normalized_query)
    timings["cache_lookup_ms"] = int((time.perf_counter() - t0) * 1000)
    if cached:
        cached["cache_hit"] = True
        cached["timings_ms"] = {
            "cache_lookup_ms": timings["cache_lookup_ms"],
            "preprocess_ms": timings["preprocess_ms"],
            "llm_ms": 0,
            "validate_ms": 0,
            "db_ms": 0,
            "total_ms": int((time.perf_counter() - started_total) * 1000),
        }
        return _with_query_context(cached, query, normalized_query, preprocessing)

    sql = None

    try:
        t_llm = time.perf_counter()
        sql = generate_sql(normalized_query)
        timings["llm_ms"] = int((time.perf_counter() - t_llm) * 1000)

        if not sql or sql == "UNKNOWN":
            return {"error": "질문이 모호합니다."}

        t_val = time.perf_counter()
        validate_sql(sql)
        sql = enforce_limit(sql)
        timings["validate_ms"] = int((time.perf_counter() - t_val) * 1000)

        try:
            t_db = time.perf_counter()
            result = run_query(sql)
            timings["db_ms"] = int((time.perf_counter() - t_db) * 1000)
        except RuntimeError as db_err:
            if "DATABASE_URL is not set" in str(db_err):
                timings["total_ms"] = int((time.perf_counter() - started_total) * 1000)
                res = _with_query_context(
                    {
                        "sql": sql,
                        "data": [],
                        "warning": "DATABASE_URL is not set. SQL only mode is active.",
                        "cache_hit": False,
                        "timings_ms": timings,
                    },
                    query,
                    normalized_query,
                    preprocessing,
                )
                set_cache(normalized_query, res)
                log_query(normalized_query, sql, True)
                return res
            raise

        timings["total_ms"] = int((time.perf_counter() - started_total) * 1000)
        res = _with_query_context(
            {
                "sql": sql,
                "data": result,
                "cache_hit": False,
                "timings_ms": timings,
            },
            query,
            normalized_query,
            preprocessing,
        )

        set_cache(normalized_query, res)
        log_query(normalized_query, sql, True)

        return res

    except Exception as e:
        # If we could not generate an initial SQL, surface the error clearly.
        if not sql:
            log_query(normalized_query, "", False)
            return {"error": str(e)}

        try:
            t_fix = time.perf_counter()
            fixed = fix_sql(normalized_query, sql, str(e))
            timings["llm_ms"] += int((time.perf_counter() - t_fix) * 1000)

            t_val = time.perf_counter()
            validate_sql(fixed)
            fixed = enforce_limit(fixed)
            timings["validate_ms"] += int((time.perf_counter() - t_val) * 1000)

            try:
                t_db = time.perf_counter()
                result = run_query(fixed)
                timings["db_ms"] += int((time.perf_counter() - t_db) * 1000)
            except RuntimeError as db_err:
                if "DATABASE_URL is not set" in str(db_err):
                    timings["total_ms"] = int((time.perf_counter() - started_total) * 1000)
                    res = _with_query_context(
                        {
                            "sql": fixed,
                            "data": [],
                            "warning": "DATABASE_URL is not set. SQL only mode is active.",
                            "cache_hit": False,
                            "timings_ms": timings,
                        },
                        query,
                        normalized_query,
                        preprocessing,
                    )
                    set_cache(normalized_query, res)
                    log_query(normalized_query, fixed, True)
                    return res
                raise

            timings["total_ms"] = int((time.perf_counter() - started_total) * 1000)
            return _with_query_context(
                {
                    "sql": fixed,
                    "data": result,
                    "cache_hit": False,
                    "timings_ms": timings,
                },
                query,
                normalized_query,
                preprocessing,
            )

        except Exception as e2:
            log_query(normalized_query, sql, False)
            return {"error": str(e2)}
