import json
import os
from urllib import error, request
import time
import re

from .prompt import build_prompt


def _ollama_generate(prompt: str) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    configured_model = os.getenv("OLLAMA_MODEL", "text2sql-local").strip()
    if not configured_model:
        raise RuntimeError("OLLAMA_MODEL is not set")

    candidates = [configured_model]
    if "-" in configured_model:
        candidates.append(configured_model.replace("-", ""))
    else:
        candidates.append(configured_model.replace("sql", "sql-"))
    # keep order while removing duplicates
    seen = set()
    models = [m for m in candidates if not (m in seen or seen.add(m))]

    last_error: Exception | None = None
    for model in models:
        payload = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
                "options": {
                    "temperature": 0.0,
                },
            }
        ).encode("utf-8")

        req = request.Request(
            f"{base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=120) as res:
                body = json.loads(res.read().decode("utf-8"))
            output = (body.get("response") or "").strip()
            if not output:
                raise RuntimeError("Ollama returned empty response")
            return output
        except error.HTTPError as e:
            detail = ""
            raw = ""
            try:
                raw = e.read().decode("utf-8")
                detail = f" | body={raw}"
            except Exception:
                pass
            # If model not found, try next candidate.
            if e.code == 404 and "not found" in raw.lower():
                last_error = RuntimeError(
                    f"Ollama model '{model}' not found. Check `ollama list` and OLLAMA_MODEL."
                )
                continue
            raise RuntimeError(f"Ollama request failed: HTTP {e.code}{detail}") from e
        except Exception as e:
            last_error = e
            break

    if last_error:
        raise RuntimeError(f"Ollama request failed: {last_error}") from last_error
    raise RuntimeError("Ollama request failed: unknown error")


def _extract_sql(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```sql", "```").strip()
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1].strip()

    # Remove common prefixes like 'SQL:' or 'Query:'
    cleaned = re.sub(r"^(sql|query|output):\s*", "", cleaned, flags=re.IGNORECASE)
    
    # Keep first statement only.
    if ";" in cleaned:
        cleaned = cleaned.split(";", 1)[0].strip()
    return cleaned


def fix_sql(query, wrong_sql, error):
    from .rag import retrieve_schema
    relevant = retrieve_schema(query)
    prompt = f"""
Fix this SQL.

Relevant schema:
{relevant}

Full schema:
v_course_info(course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom)

Column details:
- course_year: integer (1, 2, 3, 4). Use exact match: course_year = 1.
- credit_hours: string (e.g., '3', '2'). ALWAYS use strings: credit_hours = '3'.
- day_of_week: string containing Korean days (e.g., '월', '목'). Do NOT use integers.
- category: Course category (e.g., '전공(기초)', '전공(핵심)', '교양(필수)'). Use LIKE for partial matches: category LIKE '%전공(기초)%' or category LIKE '%전공%'.
- start_time: Course start time. For '오전' (morning), use start_time < '12:00'. For '오후' (afternoon), use start_time >= '12:00'.
- class_mode: Do NOT use this column unless the user explicitly asks for online/offline/real-time classes.

Rules:
- ONLY SELECT
- USE ONLY the tables and columns listed in the schema above.
- DO NOT invent or guess table names (e.g., never use 'courses', use 'v_course_info' instead).
- For string comparisons (like dept_name, subject_name, category), ALWAYS use LIKE '%word%' instead of exact match '='.
- DO NOT add filters for numeric columns (like credit_hours, course_year) unless the user explicitly mentions a value.

Query: {query}
SQL: {wrong_sql}
Error: {error}

Return only SQL.
"""
    return _extract_sql(_ollama_generate(prompt))


def generate_sql(query):
    prompt = build_prompt(query)
    return _extract_sql(_ollama_generate(prompt))


def warmup_model() -> dict:
    started = time.perf_counter()
    try:
        # very short prompt to force model load and keep it warm
        _ollama_generate("SELECT 1")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": True, "elapsed_ms": elapsed_ms}
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(e)}
