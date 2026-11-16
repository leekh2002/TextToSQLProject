from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from pathlib import Path
import os
import re
import threading

from .keyword_extract import warmup_keyword_normalizer
from .llm import warmup_model
from .mock_auth import make_access_token, verify_access_token
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
    excludeCompletedCourses: bool = False


class LoginRequest(BaseModel):
    studentNo: str = Field(min_length=1, max_length=30)


class SignupRequest(BaseModel):
    studentNo: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    departmentCode: str = Field(min_length=1, max_length=30)


def _auth_error(message: str = "Authentication failed"):
    return HTTPException(
        status_code=401,
        detail={"error": {"code": "UNAUTHORIZED", "message": message}},
    )


def _student_from_authorization(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise _auth_error("Login is required.")

    token = authorization.removeprefix("Bearer ").strip()
    student_no = verify_access_token(token)
    if not student_no:
        raise _auth_error("Invalid access token.")

    student = _find_student_by_id(student_no)
    if not student:
        raise _auth_error("Student not found.")
    return student


def _to_user_profile(row: dict) -> dict:
    student_id = str(row.get("student_id") or "")
    name = (
        row.get("name")
        or row.get("student_name")
        or row.get("user_name")
        or student_id
    )
    department_code = row.get("department_code") or row.get("dept_code") or ""
    department_name = row.get("department_name") or row.get("dept_name") or ""

    return {
        "id": str(row.get("id") or student_id),
        "studentNo": student_id,
        "name": str(name),
        "departmentCode": str(department_code or ""),
        "departmentName": str(department_name or ""),
        "grade": row.get("grade") or 0,
        "completedCourses": _completed_courses_for_student(student_id),
    }


def _completed_courses_for_student(student_id: str) -> list[dict]:
    rows = run_query(
        """
        SELECT DISTINCT subject_code
        FROM enrollment
        WHERE student_id = %s
          AND subject_code IS NOT NULL
        """,
        (student_id,),
    )
    return [
        {"subject_code": str(row["subject_code"])}
        for row in rows
        if row.get("subject_code") is not None
    ]


def _find_student_by_id(student_id: str) -> dict | None:
    rows = run_query(
        """
        SELECT
            s.student_id,
            s.dept_code,
            d.dept_name,
            s.grade
        FROM student AS s
        LEFT JOIN department AS d ON s.dept_code = d.dept_code
        WHERE s.student_id = %s
        LIMIT 1
        """,
        (student_id,),
    )
    if not rows:
        return None
    return _to_user_profile(rows[0])


DAY_ALIASES = {
    "mon": "MON",
    "monday": "MON",
    "월": "MON",
    "월요일": "MON",
    "tue": "TUE",
    "tues": "TUE",
    "tuesday": "TUE",
    "화": "TUE",
    "화요일": "TUE",
    "wed": "WED",
    "wednesday": "WED",
    "수": "WED",
    "수요일": "WED",
    "thu": "THU",
    "thur": "THU",
    "thurs": "THU",
    "thursday": "THU",
    "목": "THU",
    "목요일": "THU",
    "fri": "FRI",
    "friday": "FRI",
    "금": "FRI",
    "금요일": "FRI",
    "sat": "SAT",
    "saturday": "SAT",
    "토": "SAT",
    "토요일": "SAT",
    "sun": "SUN",
    "sunday": "SUN",
    "일": "SUN",
    "일요일": "SUN",
}
DAY_SORT_INDEX = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}
DAY_PATTERN = "|".join(
    re.escape(day)
    for day in sorted(DAY_ALIASES, key=len, reverse=True)
)
TIME_RANGE_PATTERN = re.compile(
    r"([0-2]?\d)(?::([0-5]\d))?\s*(?:-|~|–|—|to)\s*([0-2]?\d)(?::([0-5]\d))?",
    re.IGNORECASE,
)


def _normalize_day(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return DAY_ALIASES.get(normalized)


def _day_sort_value(value) -> int:
    day = _normalize_day(value) or str(value or "").strip().upper()
    return DAY_SORT_INDEX.get(day, len(DAY_SORT_INDEX))


def _format_time(hour: str, minute: str | None = None) -> str:
    return f"{int(hour):02d}:{int(minute or '00'):02d}"


def _is_valid_time_range(start: str, end: str) -> bool:
    start_hour, start_minute = [int(part) for part in start.split(":")]
    end_hour, end_minute = [int(part) for part in end.split(":")]
    return (end_hour, end_minute) > (start_hour, start_minute)


def _dedupe_schedule(slots: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for slot in slots:
        key = (slot.get("day"), slot.get("start"), slot.get("end"), slot.get("room"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(slot)
    return _sort_schedule(deduped)


def _schedule_sort_key(slot: dict) -> tuple:
    return (
        _day_sort_value(slot.get("day")),
        str(slot.get("start") or ""),
        str(slot.get("end") or ""),
        str(slot.get("room") or ""),
    )


def _sort_schedule(slots: list[dict]) -> list[dict]:
    return sorted(slots, key=_schedule_sort_key)


def _parse_credits(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def _compact_value(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "null" else text


def _split_course_list(value) -> list[str]:
    text = _compact_value(value)
    no_course_markers = {"없음", "\uc5c6\uc74c", "None", "none", "-"}
    if not text or text in no_course_markers:
        return []
    return [
        part.strip()
        for part in re.split(r"[,;/\n]+", text)
        if part.strip() and part.strip() not in no_course_markers
    ]


def _display_time(value: str) -> str:
    match = re.match(r"^([0-2]?\d):([0-5]\d)(?::[0-5]\d)?$", value)
    if not match:
        return value
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _parse_schedule_from_fields(row: dict) -> list[dict]:
    day = _normalize_day(row.get("day_of_week") or row.get("day"))
    start_value = row.get("start_time") or row.get("start")
    end_value = row.get("end_time") or row.get("end")
    if not day or start_value is None or end_value is None:
        return []

    start_match = re.search(r"([0-2]?\d)(?::([0-5]\d))?", str(start_value))
    end_match = re.search(r"([0-2]?\d)(?::([0-5]\d))?", str(end_value))
    if not start_match or not end_match:
        return []

    start = _format_time(start_match.group(1), start_match.group(2))
    end = _format_time(end_match.group(1), end_match.group(2))
    if not _is_valid_time_range(start, end):
        return []

    slot = {"day": day, "start": start, "end": end}
    room = row.get("classroom") or row.get("room")
    if room:
        slot["room"] = str(room)
    return [slot]


def _parse_schedule_from_lecture_time(lecture_time: str) -> list[dict]:
    slots = []
    for part in re.split(r"[,;/\n]+", lecture_time):
        days = [
            _normalize_day(match.group(0))
            for match in re.finditer(DAY_PATTERN, part, flags=re.IGNORECASE)
        ]
        days = [day for day in days if day]
        time_match = TIME_RANGE_PATTERN.search(part)
        if not days or not time_match:
            continue

        start = _format_time(time_match.group(1), time_match.group(2))
        end = _format_time(time_match.group(3), time_match.group(4))
        if not _is_valid_time_range(start, end):
            continue

        for day in days:
            slots.append({"day": day, "start": start, "end": end})

    return _dedupe_schedule(slots)


def _schedule_from_row(row: dict, lecture_time: str) -> list[dict]:
    slots = _parse_schedule_from_fields(row)
    if slots:
        return _dedupe_schedule(slots)
    return _parse_schedule_from_lecture_time(lecture_time)


def _lecture_time_from_row(row: dict) -> str:
    lecture_time = _compact_value(row.get("lecture_time") or row.get("table_schedule") or row.get("course_schedule"))
    if lecture_time:
        return lecture_time

    day = _compact_value(row.get("day_of_week") or row.get("day"))
    start = _compact_value(row.get("start_time") or row.get("start"))
    end = _compact_value(row.get("end_time") or row.get("end"))
    if not day or not start or not end:
        return ""
    start = _display_time(start)
    end = _display_time(end)
    return f"{day} {start}-{end}"


def _lecture_time_sort_key(value: str) -> tuple:
    text = str(value or "").strip()
    day_match = re.search(DAY_PATTERN, text, flags=re.IGNORECASE)
    time_match = re.search(r"([0-2]?\d)(?::([0-5]\d))?", text)
    start = ""
    if time_match:
        start = _format_time(time_match.group(1), time_match.group(2))
    return (
        _day_sort_value(day_match.group(0) if day_match else ""),
        start,
        text,
    )


def _location_from_row(row: dict) -> str:
    return _compact_value(row.get("classroom") or row.get("room"))


def _course_detail_items(row: dict) -> list[dict]:
    labels = [
        ("course_year", "학년"),
        ("subject_code", "과목코드"),
        ("section", "분반"),
        ("subject_name", "과목명"),
        ("category", "이수구분"),
        ("credit_hours", "학점"),
        ("target_year", "대상학년"),
        ("professor", "교수"),
        ("capacity", "정원"),
        ("enrolled", "수강인원"),
        ("grading_method", "성적평가"),
        ("eval_type", "평가방식"),
        ("class_mode", "수업방식"),
        ("dept_name", "학과"),
        ("day_of_week", "요일"),
        ("start_time", "시작"),
        ("end_time", "종료"),
        ("table_schedule", "시간표"),
        ("classroom", "강의실"),
        ("prereq_subject_codes", "선수과목 코드"),
        ("prereq_subject_names", "선수과목명"),
    ]
    details = []
    for key, label in labels:
        value = _compact_value(row.get(key))
        if value:
            details.append({"label": label, "value": value})
    return details


def _merge_course_item(existing: dict, item: dict) -> dict:
    seen_slots = {
        (slot.get("day"), slot.get("start"), slot.get("end"), slot.get("room"))
        for slot in existing.get("schedule", [])
    }
    for slot in item.get("schedule", []):
        key = (slot.get("day"), slot.get("start"), slot.get("end"), slot.get("room"))
        if key not in seen_slots:
            existing["schedule"].append(slot)
            seen_slots.add(key)

    existing_times = [time for time in existing.get("lectureTime", "").split(", ") if time]
    for time in [time for time in item.get("lectureTime", "").split(", ") if time]:
        if time not in existing_times:
            existing_times.append(time)
    existing["lectureTime"] = ", ".join(sorted(existing_times, key=_lecture_time_sort_key))
    existing["schedule"] = _sort_schedule(existing.get("schedule", []))

    existing_locations = [location for location in existing.get("locationText", "").split(", ") if location]
    for location in [location for location in item.get("locationText", "").split(", ") if location]:
        if location not in existing_locations:
            existing_locations.append(location)
    existing["locationText"] = ", ".join(existing_locations)

    for key in ("prerequisiteCourseCodes", "prerequisiteCourseNames"):
        existing_values = existing.get(key, [])
        for value in item.get(key, []):
            if value not in existing_values:
                existing_values.append(value)
        existing[key] = existing_values

    existing["details"] = _merge_detail_items(
        existing.get("details", []),
        item.get("details", []),
    )

    return existing


def _merge_detail_value(existing_value: str, next_value: str) -> str:
    parts = [part.strip() for part in str(existing_value or "").split(",") if part.strip()]
    for part in [part.strip() for part in str(next_value or "").split(",") if part.strip()]:
        if part not in parts:
            parts.append(part)
    return ", ".join(parts)


def _merge_detail_items(existing_details: list[dict], next_details: list[dict]) -> list[dict]:
    merged = []
    by_label = {}

    for detail in [*existing_details, *next_details]:
        label = detail.get("label")
        value = detail.get("value")
        if not label or value is None or value == "":
            continue
        if label in by_label:
            by_label[label]["value"] = _merge_detail_value(by_label[label]["value"], str(value))
        else:
            merged_detail = {"label": label, "value": str(value)}
            merged.append(merged_detail)
            by_label[label] = merged_detail

    return merged


def _group_course_items(rows: list[dict]) -> list[dict]:
    grouped = {}
    for row in rows:
        item = _to_course_item(row)
        key = item["courseId"]
        grouped[key] = _merge_course_item(grouped[key], item) if key in grouped else item
    return list(grouped.values())


def _to_course_item(row: dict):
    subject_code = row.get("subject_code") or row.get("course_id") or ""
    section = row.get("section") or ""
    course_id = f"{subject_code}-{section}" if section else subject_code
    capacity = row.get("capacity")
    enrolled = row.get("enrolled")

    tags = []
    lecture_time = _lecture_time_from_row(row)
    location = _location_from_row(row)
    if lecture_time:
        tags.append(lecture_time)
    category = _compact_value(row.get("category"))
    if category:
        tags.append(category)

    return {
        "courseId": str(course_id or ""),
        "name": str(row.get("subject_name") or row.get("course_name") or course_id or "Untitled"),
        "departmentCode": str(row.get("dept_code") or ""),
        "departmentName": row.get("dept_name"),
        "credits": _parse_credits(row.get("credit_hours") or row.get("credits")),
        "professor": str(row.get("professor") or "-"),
        "capacity": capacity,
        "enrolled": enrolled,
        "schedule": _schedule_from_row(row, lecture_time),
        "lectureTime": lecture_time,
        "locationText": location,
        "section": str(section),
        "tags": tags,
        "prerequisiteCourseCodes": _split_course_list(row.get("prereq_subject_codes")),
        "prerequisiteCourseNames": _split_course_list(row.get("prereq_subject_names")),
        "details": _course_detail_items(row),
    }


@app.get("/api/v1/health")
def health():
    return {"ok": True}


@app.on_event("startup")
def startup_warmup():
    app.state.warmup = {"ok": False, "status": "warming"}

    def run_warmup():
        app.state.warmup = {
            "ok": True,
            "llm": warmup_model(),
            "keyword_normalizer": warmup_keyword_normalizer(),
        }

    threading.Thread(target=run_warmup, daemon=True).start()


@app.get("/api/v1/warmup")
def warmup_status():
    return getattr(app.state, "warmup", {"ok": False, "error": "warmup not run"})


@app.post("/api/v1/auth/login")
def login(req: LoginRequest):
    student_no = req.studentNo.strip()
    student = _find_student_by_id(student_no)
    if not student:
        raise _auth_error("등록되지 않은 학번입니다.")

    return {
        "accessToken": make_access_token(student["studentNo"]),
        "expiresIn": 60 * 60 * 8,
        "user": student,
    }


@app.post("/api/v1/auth/signup")
def signup(_: SignupRequest):
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "PORTAL_SIGNUP_UNAVAILABLE",
                "message": "포털 연동 계정은 회원가입 없이 충남대 포털 로그인으로 이용합니다.",
            }
        },
    )


@app.post("/api/v1/auth/logout")
def logout():
    return {"ok": True}


@app.get("/api/v1/students/me")
def get_me(authorization: str | None = Header(default=None)):
    return {"user": _student_from_authorization(authorization)}


@app.get("/api/v1/students/me/profile")
def get_my_profile(authorization: str | None = Header(default=None)):
    return _student_from_authorization(authorization)


@app.get("/api/v1/courses")
def list_courses(
    page: int = 1,
    pageSize: int = 100,
    keyword: str | None = None,
):
    page = max(page, 1)
    pageSize = min(max(pageSize, 1), 200)
    offset = (page - 1) * pageSize
    filters = []
    params = []
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        filters.append("subject_name ILIKE %s")
        params.append(f"%{normalized_keyword}%")

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM v_course_info
        {where_clause}
    """
    sql = f"""
        WITH page_course_keys AS (
            SELECT subject_code, section
            FROM v_course_info
            {where_clause}
            GROUP BY subject_code, section
            ORDER BY subject_code, section
            LIMIT %s OFFSET %s
        )
        SELECT
            ci.course_year,
            ci.subject_code,
            ci.section,
            ci.subject_name,
            ci.category,
            ci.credit_hours,
            ci.target_year,
            ci.professor,
            ci.capacity,
            ci.enrolled,
            ci.grading_method,
            ci.eval_type,
            ci.class_mode,
            ci.dept_name,
            ci.day_of_week,
            ci.start_time,
            ci.end_time,
            ci.classroom,
            ci.prereq_subject_codes,
            ci.prereq_subject_names
        FROM page_course_keys AS pk
        JOIN v_course_info AS ci
          ON ci.subject_code = pk.subject_code
         AND ci.section IS NOT DISTINCT FROM pk.section
        ORDER BY
            ci.subject_code,
            ci.section,
            CASE ci.day_of_week
                WHEN '월' THEN 1
                WHEN '화' THEN 2
                WHEN '수' THEN 3
                WHEN '목' THEN 4
                WHEN '금' THEN 5
                WHEN '토' THEN 6
                ELSE 7
            END,
            ci.start_time NULLS LAST
    """
    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM (
            SELECT subject_code, section
            FROM v_course_info
            {where_clause}
            GROUP BY subject_code, section
        ) AS course_keys
    """

    try:
        rows = run_query(sql, (*params, pageSize, offset))
        total_rows = run_query(count_sql, tuple(params))
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

    items = _group_course_items(rows)[:pageSize]
    total = int(total_rows[0]["total"]) if total_rows else len(items) + offset

    return {
        "items": items,
        "page": page,
        "pageSize": pageSize,
        "total": total,
    }


def _run_query(req: QueryRequest, authorization: str | None = None):
    try:
        student_no = None
        use_v2 = os.getenv("T2S_PIPELINE", "v1").strip().lower() == "v2"
        if req.excludeCompletedCourses:
            student_no = _student_from_authorization(authorization)["studentNo"]
        elif use_v2 and authorization:
            # Anonymous queries must keep working with a stale token.
            try:
                student_no = _student_from_authorization(authorization)["studentNo"]
            except Exception:
                student_no = None
        if use_v2:
            from .t2s.pipeline import run_v2

            return run_v2(
                req.query,
                exclude_completed_courses=req.excludeCompletedCourses,
                student_id=student_no,
            )
        return process(
            req.query,
            exclude_completed_courses=req.excludeCompletedCourses,
            student_id=student_no,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/chat/query")
def chat_query_api(req: QueryRequest, authorization: str | None = Header(default=None)):
    return _run_query(req, authorization)


@app.post("/api/v1/query")
def query_api(req: QueryRequest, authorization: str | None = Header(default=None)):
    return _run_query(req, authorization)
