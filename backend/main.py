from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from pathlib import Path

from .keyword_extract import warmup_keyword_normalizer
from .llm import warmup_model
from .process import process
from .db import run_query

load_dotenv()  # load workspace .env if present
load_dotenv(Path(__file__).with_name(".env"), override=False)  # load backend-specific env

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


def _to_course_item(row: dict):
    subject_code = row.get("subject_code") or row.get("course_id") or ""
    section = row.get("section") or ""
    course_id = f"{subject_code}-{section}" if section else subject_code
    capacity = row.get("capacity")
    enrolled = row.get("enrolled")

    tags = []
    lecture_time = row.get("lecture_time") or ""
    if lecture_time:
        tags.append(str(lecture_time))

    return {
        "courseId": str(course_id or ""),
        "name": str(row.get("subject_name") or row.get("course_name") or course_id or "Untitled"),
        "departmentCode": str(row.get("dept_code") or ""),
        "departmentName": row.get("dept_name"),
        "credits": row.get("credit_hours") or row.get("credits") or 0,
        "professor": str(row.get("professor") or "-"),
        "capacity": capacity,
        "enrolled": enrolled,
        "schedule": [],
        "lectureTime": str(lecture_time),
        "section": str(section),
    }


@app.get("/api/v1/health")
def health():
    return {"ok": True}


@app.on_event("startup")
def startup_warmup():
    # Warm up local models once to reduce first-query latency.
    app.state.warmup = {
        "llm": warmup_model(),
        "keyword_normalizer": warmup_keyword_normalizer(),
    }


@app.get("/api/v1/warmup")
def warmup_status():
    return getattr(app.state, "warmup", {"ok": False, "error": "warmup not run"})


@app.get("/api/v1/courses")
def list_courses(
    page: int = 1,
    pageSize: int = 100,
):
    page = max(page, 1)
    pageSize = min(max(pageSize, 1), 200)
    offset = (page - 1) * pageSize
    sql = f"""
        SELECT
            co.subject_code,
            co.section,
            co.capacity,
            co.enrolled,
            co.lecture_time,
            co.professor,
            co.dept_code,
            s.subject_name,
            s.credit_hours,
            d.dept_name
        FROM course_offerings co
        LEFT JOIN subject s ON s.subject_code = co.subject_code
        LEFT JOIN department d ON d.dept_code = co.dept_code
        ORDER BY co.subject_code, co.section
        LIMIT {pageSize} OFFSET {offset}
    """

    try:
        rows = run_query(sql)
    except RuntimeError as e:
        if "DATABASE_URL is not set" in str(e):
            return {
                "items": [],
                "page": page,
                "pageSize": pageSize,
                "total": 0,
                "warning": "DATABASE_URL is not set. Mock course data should be used by the frontend.",
            }
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "items": [_to_course_item(row) for row in rows],
        "page": page,
        "pageSize": pageSize,
        "total": len(rows) + offset,
    }


@app.post("/api/v1/query")
def query_api(req: QueryRequest):
    try:
        return process(req.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
