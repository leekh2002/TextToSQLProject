import datetime
import os
from pathlib import Path

def log_query(q, sql, success):
    log_path = Path(os.getenv("QUERY_LOG_PATH", "backend-log.txt"))
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now()} | {q} | {sql} | {success}\n")
