import os

import psycopg2

def run_query(sql):
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:4231@localhost:5432/postgres").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")

    conn = psycopg2.connect(dsn)

    cur = conn.cursor()
    cur.execute(sql)

    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()

    result = [dict(zip(cols, r)) for r in rows]

    cur.close()
    conn.close()

    return result
