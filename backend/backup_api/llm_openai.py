import os

from openai import OpenAI

from ..prompt import build_prompt


def _get_client():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


def generate_sql(query):
    prompt = build_prompt(query)
    model = os.getenv("OPENAI_TEXT_TO_SQL_MODEL", "gpt-4o-mini").strip()

    client = _get_client()
    res = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    return (res.choices[0].message.content or "").strip()


def fix_sql(query, wrong_sql, error):
    prompt = f"""
Fix this SQL.

Query: {query}
SQL: {wrong_sql}
Error: {error}

Return only SQL.
"""

    model = os.getenv("OPENAI_TEXT_TO_SQL_MODEL", "gpt-4o-mini").strip()
    client = _get_client()
    res = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    return res.choices[0].message.content.strip()
