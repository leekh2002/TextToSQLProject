# Text-to-SQL 골든 평가셋 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `backend/eval/` 아래에 text-to-sql 파이프라인(`process()`) 전체를 실제 DB/Ollama에 대해 실행해 정확도를 측정하는 43개 골든 쿼리셋과 CLI 실행기를 만든다.

**Architecture:** 채점 로직(`grading.py`)과 데이터(`golden_queries.json`)와 CLI(`run_eval.py`)를 분리한다. `grading.py`의 순수 비교 함수는 DB 없이 유닛 테스트하고, `run_eval.py`는 실제 `process()`를 호출해 카테고리별/전체 정확도를 콘솔 표 + JSON 리포트로 출력한다. 기존 파이프라인 코드는 전혀 수정하지 않는다.

**Tech Stack:** Python 3.10+, pytest(이미 환경에 설치돼 있음, `backend/requirements.txt`에 추가), sqlglot(기존 `validate.py`가 이미 사용 중, 재사용), psycopg2(기존 `backend/db.py`의 `run_query` 재사용).

**Spec:** `docs/superpowers/specs/2026-09-07-text-to-sql-eval-set-design.md`

## Global Constraints

- 기존 파이프라인 코드(`backend/process.py`, `backend/llm.py`, `backend/prompt.py`, `backend/validate.py`, `backend/db.py` 등)는 수정하지 않는다 — 신규 파일만 추가한다.
- 모든 실행은 저장소 루트에서 `python -m backend.eval.<module>` 형태로 한다 (기존 `python -m uvicorn backend.main:app` 관례와 동일, `package.json`의 `dev:backend` 스크립트 참고).
- `execution` 채점의 `reference_sql`은 실제 DB(`postgresql://postgres:***@localhost:5432/postgres`)에 대해 사람이 직접 실행/검산한 값만 사용한다 (스펙 문서의 "환경 확인 결과" 절 참고). 이 계획 문서에 적힌 모든 `reference_sql`과 기대 행 수는 이미 실제 DB에서 검증됨.
- `v_course_info`는 `course_schedule`/`course_prerequisite`와의 JOIN으로 인해 같은 과목이 여러 행으로 중복될 수 있다(팬아웃). 이 때문에 `compare_execution`은 **순서 무관 집합 비교**를 기본으로 한다(중복 행은 집합에서 자연히 합쳐짐).
- 컬럼 비교는 reference/generated 두 결과의 **공통 컬럼 교집합**으로 한다 — 생성된 SQL이 prompt.py가 지시한 19개 컬럼 전체를 선택하지 않는 경우에도 공정하게 비교하기 위함.

---

### Task 1: 패키지 스켈레톤 + 실행 비교(execution) 채점 로직

**Files:**
- Create: `backend/eval/__init__.py`
- Create: `backend/eval/grading.py`
- Test: `backend/eval/test_grading.py`
- Modify: `backend/requirements.txt` (pytest 추가)

**Interfaces:**
- Produces:
  - `common_columns(rows_a: list[dict], rows_b: list[dict]) -> list[str]`
  - `project_rows(rows: list[dict], columns: list[str]) -> list[tuple]`
  - `compare_execution(reference_rows: list[dict], generated_rows: list[dict], order_sensitive: bool = False) -> tuple[bool, str | None]`

- [ ] **Step 1: `backend/requirements.txt`에 pytest 추가**

`backend/requirements.txt` 마지막 줄에 추가:
```
pytest
```

- [ ] **Step 2: 패키지 초기화 파일 생성**

`backend/eval/__init__.py`을 내용 없이(빈 파일로) 생성한다. `backend/__init__.py`도 동일하게 빈 파일이므로 기존 관례를 따른다.

- [ ] **Step 3: 실패하는 테스트 작성**

`backend/eval/test_grading.py`:
```python
from backend.eval.grading import common_columns, compare_execution, project_rows


def test_common_columns_returns_intersection():
    rows_a = [{"subject_code": "1214-3033", "enrolled": 40}]
    rows_b = [{"subject_code": "1214-3033", "capacity": 45}]
    assert common_columns(rows_a, rows_b) == ["subject_code"]


def test_common_columns_empty_when_no_rows():
    assert common_columns([], [{"a": 1}]) == []
    assert common_columns([{"a": 1}], []) == []


def test_project_rows_extracts_values_in_column_order():
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert project_rows(rows, ["b", "a"]) == [(2, 1), (4, 3)]


def test_compare_execution_matches_when_row_sets_equal_ignoring_order():
    reference_rows = [
        {"subject_code": "1214-3033", "section": "00"},
        {"subject_code": "1214-3033", "section": "01"},
    ]
    generated_rows = [
        {"subject_code": "1214-3033", "section": "01"},
        {"subject_code": "1214-3033", "section": "00"},
    ]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is True
    assert reason is None


def test_compare_execution_ignores_exact_duplicate_rows():
    reference_rows = [{"subject_code": "1214-3033", "section": "00"}]
    generated_rows = [
        {"subject_code": "1214-3033", "section": "00"},
        {"subject_code": "1214-3033", "section": "00"},
    ]
    ok, _ = compare_execution(reference_rows, generated_rows)
    assert ok is True


def test_compare_execution_detects_missing_row():
    reference_rows = [
        {"subject_code": "A", "section": "00"},
        {"subject_code": "B", "section": "00"},
    ]
    generated_rows = [{"subject_code": "A", "section": "00"}]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is False
    assert "누락" in reason


def test_compare_execution_detects_extra_row():
    reference_rows = [{"subject_code": "A", "section": "00"}]
    generated_rows = [
        {"subject_code": "A", "section": "00"},
        {"subject_code": "B", "section": "00"},
    ]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is False
    assert "추가" in reason


def test_compare_execution_both_empty_is_match():
    ok, reason = compare_execution([], [])
    assert ok is True
    assert reason is None


def test_compare_execution_no_common_columns_fails():
    reference_rows = [{"subject_code": "A"}]
    generated_rows = [{"different_column": "A"}]
    ok, reason = compare_execution(reference_rows, generated_rows)
    assert ok is False
    assert "겹치지 않습니다" in reason


def test_compare_execution_order_sensitive_detects_reordering():
    reference_rows = [{"n": 1}, {"n": 2}]
    generated_rows = [{"n": 2}, {"n": 1}]
    ok, _ = compare_execution(reference_rows, generated_rows, order_sensitive=True)
    assert ok is False
```

- [ ] **Step 4: 테스트 실행해서 실패 확인**

Run: `python -m pytest backend/eval/test_grading.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.eval.grading'` (또는 `ImportError`)

- [ ] **Step 5: `grading.py`에 최소 구현 작성**

`backend/eval/grading.py`:
```python
from __future__ import annotations


def common_columns(rows_a: list[dict], rows_b: list[dict]) -> list[str]:
    if not rows_a or not rows_b:
        return []
    keys_a = set(rows_a[0].keys())
    keys_b = set(rows_b[0].keys())
    return sorted(keys_a & keys_b)


def project_rows(rows: list[dict], columns: list[str]) -> list[tuple]:
    return [tuple(row.get(column) for column in columns) for row in rows]


def compare_execution(
    reference_rows: list[dict],
    generated_rows: list[dict],
    order_sensitive: bool = False,
) -> tuple[bool, str | None]:
    if not reference_rows and not generated_rows:
        return True, None

    columns = common_columns(reference_rows, generated_rows)
    if not columns:
        reference_cols = sorted(reference_rows[0].keys()) if reference_rows else []
        generated_cols = sorted(generated_rows[0].keys()) if generated_rows else []
        return False, (
            f"컬럼이 겹치지 않습니다: reference={reference_cols}, generated={generated_cols}"
        )

    reference_projection = project_rows(reference_rows, columns)
    generated_projection = project_rows(generated_rows, columns)

    if order_sensitive:
        ok = reference_projection == generated_projection
    else:
        ok = set(reference_projection) == set(generated_projection)

    if ok:
        return True, None

    reference_set = set(reference_projection)
    generated_set = set(generated_projection)
    missing = reference_set - generated_set
    extra = generated_set - reference_set
    reason_parts = [f"reference={len(reference_rows)}행 vs generated={len(generated_rows)}행"]
    if missing:
        reason_parts.append(f"누락된 행 {len(missing)}개(예: {next(iter(missing))})")
    if extra:
        reason_parts.append(f"추가된 행 {len(extra)}개(예: {next(iter(extra))})")
    return False, "; ".join(reason_parts)
```

- [ ] **Step 6: 테스트 실행해서 통과 확인**

Run: `python -m pytest backend/eval/test_grading.py -v`
Expected: 모든 테스트 PASS (10개)

- [ ] **Step 7: 커밋**

```bash
git add backend/eval/__init__.py backend/eval/grading.py backend/eval/test_grading.py backend/requirements.txt
git commit -m "test: add execution-comparison grading for text-to-sql eval set"
```

---

### Task 2: 구조 검증(structural) 채점 로직

**Files:**
- Modify: `backend/eval/grading.py`
- Modify: `backend/eval/test_grading.py`

**Interfaces:**
- Consumes:
  - `backend.validate.extract_table_references(sql: str) -> set[str]` (기존 함수, `backend/validate.py:47`)
  - `backend.validate.extract_table_aliases(sql: str, table_name: str) -> set[str]` (기존 함수, `backend/validate.py:58`)
  - `backend.validate.has_scoped_student_filter(sql: str, table_aliases: set[str], requested_student_id: str | None) -> bool` (기존 함수, `backend/validate.py:118`)
- Produces:
  - `check_required_tables(sql: str, required_tables: list[str]) -> tuple[bool, str | None]`
  - `check_required_columns(sql: str, required_columns: list[str]) -> tuple[bool, str | None]`
  - `check_student_scoped(sql: str, student_id: str | None) -> tuple[bool, str | None]`
  - `check_structural(sql: str, structural_checks: dict, student_id: str | None) -> tuple[bool, str | None]`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/eval/test_grading.py`에 추가:
```python
from backend.eval.grading import (
    check_required_columns,
    check_required_tables,
    check_structural,
    check_student_scoped,
)


def test_check_required_tables_passes_when_all_present():
    sql = "SELECT * FROM student s JOIN required_subject r ON s.dept_code = r.dept_code LIMIT 50"
    ok, reason = check_required_tables(sql, ["student", "required_subject"])
    assert ok is True
    assert reason is None


def test_check_required_tables_fails_when_missing():
    sql = "SELECT * FROM student LIMIT 50"
    ok, reason = check_required_tables(sql, ["student", "required_subject"])
    assert ok is False
    assert "required_subject" in reason


def test_check_required_columns_passes_with_alias():
    sql = "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"
    ok, reason = check_required_columns(sql, ["student.grade"])
    assert ok is True
    assert reason is None


def test_check_required_columns_fails_when_column_absent():
    sql = "SELECT s.dept_code FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"
    ok, reason = check_required_columns(sql, ["student.grade"])
    assert ok is False
    assert "student.grade" in reason


def test_check_student_scoped_passes_with_matching_literal():
    sql = "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"
    ok, reason = check_student_scoped(sql, "202102671")
    assert ok is True
    assert reason is None


def test_check_student_scoped_fails_without_filter():
    sql = "SELECT s.grade FROM student AS s LIMIT 50"
    ok, reason = check_student_scoped(sql, "202102671")
    assert ok is False
    assert "스코프" in reason


def test_check_structural_runs_all_checks_in_order():
    structural_checks = {
        "required_tables": ["student"],
        "required_columns": ["student.grade"],
        "student_scoped": True,
    }
    good_sql = "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"
    ok, reason = check_structural(good_sql, structural_checks, "202102671")
    assert ok is True
    assert reason is None

    missing_table_sql = "SELECT 1 AS grade LIMIT 50"
    ok, reason = check_structural(missing_table_sql, structural_checks, "202102671")
    assert ok is False
    assert "student" in reason
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest backend/eval/test_grading.py -v`
Expected: 새로 추가한 테스트들 FAIL — `ImportError: cannot import name 'check_required_tables'`

- [ ] **Step 3: `grading.py`에 구조 검증 함수 추가**

`backend/eval/grading.py` 상단 import를 다음으로 교체:
```python
from __future__ import annotations

import re

from ..validate import (
    extract_table_aliases,
    extract_table_references,
    has_scoped_student_filter,
)
```

파일 끝에 추가:
```python
def check_required_tables(sql: str, required_tables: list[str]) -> tuple[bool, str | None]:
    referenced = extract_table_references(sql)
    missing = [table for table in required_tables if table not in referenced]
    if missing:
        return False, f"필요한 테이블이 SQL에 없습니다: {', '.join(missing)}"
    return True, None


def check_required_columns(sql: str, required_columns: list[str]) -> tuple[bool, str | None]:
    lowered_sql = sql.lower()
    missing = []
    for qualified_column in required_columns:
        table, separator, column = qualified_column.partition(".")
        if not separator:
            table, column = None, table

        patterns = []
        if table:
            aliases = extract_table_aliases(sql, table)
            patterns.extend(rf"\b{re.escape(alias)}\.{re.escape(column)}\b" for alias in aliases)
        patterns.append(rf"\b{re.escape(column)}\b")

        if not any(re.search(pattern, lowered_sql) for pattern in patterns):
            missing.append(qualified_column)

    if missing:
        return False, f"필요한 컬럼 참조가 SQL에 없습니다: {', '.join(missing)}"
    return True, None


def check_student_scoped(sql: str, student_id: str | None) -> tuple[bool, str | None]:
    student_aliases = extract_table_aliases(sql, "student")
    if not has_scoped_student_filter(sql, student_aliases, student_id):
        return False, "student 테이블 조회가 요청된 학생 학번으로 스코프되지 않았습니다."
    return True, None


def check_structural(
    sql: str,
    structural_checks: dict,
    student_id: str | None,
) -> tuple[bool, str | None]:
    ok, reason = check_required_tables(sql, structural_checks.get("required_tables", []))
    if not ok:
        return ok, reason

    ok, reason = check_required_columns(sql, structural_checks.get("required_columns", []))
    if not ok:
        return ok, reason

    if structural_checks.get("student_scoped"):
        ok, reason = check_student_scoped(sql, student_id)
        if not ok:
            return ok, reason

    return True, None
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest backend/eval/test_grading.py -v`
Expected: 전체 PASS (17개)

- [ ] **Step 5: 커밋**

```bash
git add backend/eval/grading.py backend/eval/test_grading.py
git commit -m "test: add structural grading checks reusing validate.py helpers"
```

---

### Task 3: `grade_case` 오케스트레이션 (expects_error + execution/structural 분기)

**Files:**
- Modify: `backend/eval/grading.py`
- Modify: `backend/eval/test_grading.py`

**Interfaces:**
- Consumes:
  - `backend.db.run_query(sql: str, params=None) -> list[dict]` (기존 함수, `backend/db.py:5`) — `grading.py`에서 `from ..db import run_query`로 임포트해 모듈 전역에서 참조. 테스트에서는 `monkeypatch.setattr("backend.eval.grading.run_query", ...)`로 대체한다.
- Produces:
  - `grade_case(case: dict, result: dict) -> dict` — 반환값은 `{"ok": bool, "reason": str | None}`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/eval/test_grading.py`에 추가:
```python
from backend.eval import grading
from backend.eval.grading import grade_case


def test_grade_case_expects_error_passes_when_process_returns_error():
    case = {"id": "x", "grading": "structural", "expects_error": True, "structural_checks": {}}
    result = {"error": "질문이 모호합니다."}
    grade = grade_case(case, result)
    assert grade == {"ok": True, "reason": None}


def test_grade_case_expects_error_fails_when_sql_was_generated():
    case = {"id": "x", "grading": "structural", "expects_error": True, "structural_checks": {}}
    result = {"sql": "SELECT 1 LIMIT 50", "data": []}
    grade = grade_case(case, result)
    assert grade["ok"] is False


def test_grade_case_fails_when_unexpected_error_occurs():
    case = {"id": "x", "grading": "execution", "expects_error": False, "reference_sql": "SELECT 1"}
    result = {"error": "허용되지 않은 테이블 참조: foo"}
    grade = grade_case(case, result)
    assert grade["ok"] is False
    assert "예상치 못한 오류" in grade["reason"]


def test_grade_case_structural_delegates_to_check_structural():
    case = {
        "id": "x",
        "grading": "structural",
        "expects_error": False,
        "student_id": "202102671",
        "structural_checks": {"required_tables": ["student"], "student_scoped": True},
    }
    result = {"sql": "SELECT s.grade FROM student AS s WHERE s.student_id = '202102671' LIMIT 50"}
    grade = grade_case(case, result)
    assert grade == {"ok": True, "reason": None}


def test_grade_case_execution_uses_run_query_for_reference_sql(monkeypatch):
    def fake_run_query(sql, params=None):
        assert sql == "SELECT subject_code FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%'"
        return [{"subject_code": "1214-3033"}]

    monkeypatch.setattr(grading, "run_query", fake_run_query)

    case = {
        "id": "x",
        "grading": "execution",
        "expects_error": False,
        "reference_sql": "SELECT subject_code FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%'",
        "order_sensitive": False,
    }
    result = {"sql": "SELECT subject_code FROM v_course_info WHERE dept_name = '컴퓨터융합학부'", "data": [{"subject_code": "1214-3033"}]}
    grade = grade_case(case, result)
    assert grade == {"ok": True, "reason": None}


def test_grade_case_unknown_grading_mode_raises():
    case = {"id": "x", "grading": "not-a-real-mode", "expects_error": False}
    result = {"sql": "SELECT 1", "data": []}
    try:
        grade_case(case, result)
        assert False, "ValueError를 기대했지만 예외가 발생하지 않았습니다."
    except ValueError:
        pass
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest backend/eval/test_grading.py -v`
Expected: 새 테스트들 FAIL — `ImportError: cannot import name 'grade_case'`

- [ ] **Step 3: `grading.py`에 `grade_case` 추가**

`backend/eval/grading.py` import 블록의 `from ..validate import (...)` 아래에 추가:
```python
from ..db import run_query
```

파일 끝에 추가:
```python
def _to_grade_dict(outcome: tuple[bool, str | None]) -> dict:
    ok, reason = outcome
    return {"ok": ok, "reason": reason}


def grade_case(case: dict, result: dict) -> dict:
    if case.get("expects_error"):
        if isinstance(result, dict) and result.get("error"):
            return {"ok": True, "reason": None}
        return {"ok": False, "reason": "오류가 예상되었지만 SQL이 정상 생성되었습니다."}

    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "reason": f"예상치 못한 오류: {result['error']}"}

    sql = result.get("sql", "")

    if case["grading"] == "structural":
        return _to_grade_dict(
            check_structural(sql, case.get("structural_checks", {}), case.get("student_id"))
        )

    if case["grading"] == "execution":
        reference_rows = run_query(case["reference_sql"])
        generated_rows = result.get("data", [])
        return _to_grade_dict(
            compare_execution(reference_rows, generated_rows, case.get("order_sensitive", False))
        )

    raise ValueError(f"알 수 없는 grading 값: {case['grading']}")
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest backend/eval/test_grading.py -v`
Expected: 전체 PASS (23개)

- [ ] **Step 5: 커밋**

```bash
git add backend/eval/grading.py backend/eval/test_grading.py
git commit -m "feat: add grade_case orchestration for text-to-sql eval set"
```

---

### Task 4: 골든 쿼리셋 데이터 (`golden_queries.json`) + 데이터 무결성 테스트

**Files:**
- Create: `backend/eval/golden_queries.json`
- Create: `backend/eval/test_golden_queries.py`

**Interfaces:**
- Produces: `backend/eval/golden_queries.json` — Task 5의 `run_eval.py`가 로드해서 사용하는 43개 케이스 배열. 각 케이스는 최소 `id`, `category`, `query`, `grading`(`"execution"` 또는 `"structural"`), `expects_error`(bool) 키를 가진다. `grading == "execution"`이면 `reference_sql`이 non-null이어야 하고, `expects_error == false`이고 `grading == "structural"`이면 `structural_checks`가 비어있지 않아야 한다.

- [ ] **Step 1: 실패하는 데이터 무결성 테스트 작성**

`backend/eval/test_golden_queries.py`:
```python
import json
from pathlib import Path

GOLDEN_QUERIES_PATH = Path(__file__).with_name("golden_queries.json")
VALID_GRADING_MODES = {"execution", "structural"}
REQUIRED_KEYS = {
    "id",
    "category",
    "query",
    "grading",
    "reference_sql",
    "order_sensitive",
    "expects_error",
    "student_id",
    "exclude_completed_courses",
    "structural_checks",
    "notes",
}


def _load_cases():
    with open(GOLDEN_QUERIES_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def test_golden_queries_file_has_43_cases():
    cases = _load_cases()
    assert len(cases) == 43


def test_all_case_ids_are_unique():
    cases = _load_cases()
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))


def test_every_case_has_required_keys():
    cases = _load_cases()
    for case in cases:
        missing = REQUIRED_KEYS - set(case.keys())
        assert not missing, f"{case.get('id')}: 누락된 키 {missing}"


def test_grading_mode_is_valid():
    cases = _load_cases()
    for case in cases:
        assert case["grading"] in VALID_GRADING_MODES, case["id"]


def test_execution_cases_have_reference_sql():
    cases = _load_cases()
    for case in cases:
        if case["grading"] == "execution":
            assert case["reference_sql"], f"{case['id']}: reference_sql이 비어있습니다"
            assert case["reference_sql"].strip().lower().startswith("select"), case["id"]


def test_structural_non_error_cases_have_checks():
    cases = _load_cases()
    for case in cases:
        if case["grading"] == "structural" and not case["expects_error"]:
            checks = case["structural_checks"]
            assert checks, f"{case['id']}: structural_checks가 비어있습니다"
            assert checks.get("required_tables"), f"{case['id']}: required_tables가 비어있습니다"


def test_category_counts_match_design():
    cases = _load_cases()
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {
        "course_filter": 15,
        "exclude_completed_courses": 5,
        "prerequisite": 5,
        "enrollment_aggregate": 5,
        "personalized_lookup": 5,
        "graduation_requirement": 3,
        "ambiguous_reject": 5,
    }
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest backend/eval/test_golden_queries.py -v`
Expected: FAIL — `FileNotFoundError` (golden_queries.json이 아직 없음)

- [ ] **Step 3: `golden_queries.json` 생성**

`backend/eval/golden_queries.json` (43개 케이스 전체, 각 `reference_sql`과 기대 행 수는 실제 DB에서 검증된 값):

```json
[
  {
    "id": "course_filter_01",
    "category": "course_filter",
    "query": "컴퓨터융합학부 3학년 대상 전공(핵심) 과목 중에서 목요일 수업 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND category LIKE '%전공(핵심)%' AND target_year = 3 AND day_of_week = '목'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "target_year(대상학년)은 prompt.py의 Column details에 문서화되어 있지 않다. course_year(개설학년)와 혼동하는지 확인하는 케이스. 실제 DB 기준 2행."
  },
  {
    "id": "course_filter_02",
    "category": "course_filter",
    "query": "데이터베이스 관련 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE subject_name LIKE '%데이터베이스%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "단순 과목명 LIKE 검색. 실제 DB 기준 10행."
  },
  {
    "id": "course_filter_03",
    "category": "course_filter",
    "query": "유정연 교수님이 가르치는 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE professor LIKE '%유정연%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "professor는 prompt.py Column details에 별도 언급이 없어 LIKE 대신 '=' exact match를 쓰는지도 확인. 실제 DB 기준 4행."
  },
  {
    "id": "course_filter_04",
    "category": "course_filter",
    "query": "컴퓨터융합학부 월요일 오전 수업 뭐 있어",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND day_of_week = '월' AND start_time < '12:00:00'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "오전/오후 range 규칙(prompt.py) 검증. 실제 DB 기준 2행."
  },
  {
    "id": "course_filter_05",
    "category": "course_filter",
    "query": "컴퓨터융합학부 1시 수업 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND start_time = '13:00:00'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "'1시'를 13:00:00으로 매핑하는 prompt.py 규칙 검증. 실제 DB 기준 19행."
  },
  {
    "id": "course_filter_06",
    "category": "course_filter",
    "query": "경제학과 전공핵심 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%경제학과%' AND category LIKE '%전공(핵심)%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "'전공핵심'을 category 값 '전공(핵심)'으로 정규화하는지 확인. 실제 DB 기준 27행."
  },
  {
    "id": "course_filter_07",
    "category": "course_filter",
    "query": "컴퓨터융합학부 과목 중에 정원이 다 찬 수업 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND enrolled >= capacity AND capacity > 0",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "capacity/enrolled 비교 조건은 prompt.py에 규칙이 없어 모델이 스스로 유추해야 함. 실제 DB 기준 23행."
  },
  {
    "id": "course_filter_08",
    "category": "course_filter",
    "query": "컴퓨터융합학부 2학년 대상 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND target_year = 2",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "target_year 미문서화 이슈(course_filter_01 참고). 실제 DB 기준 30행."
  },
  {
    "id": "course_filter_09",
    "category": "course_filter",
    "query": "알고리즘 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE subject_name LIKE '%알고리즘%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 5행."
  },
  {
    "id": "course_filter_10",
    "category": "course_filter",
    "query": "컴퓨터융합학부 수요일 오후 수업 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND day_of_week = '수' AND start_time >= '12:00:00'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 12행."
  },
  {
    "id": "course_filter_11",
    "category": "course_filter",
    "query": "컴퓨터융합학부 5시 수업 뭐 있어",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND start_time = '17:00:00'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "'5시'를 17:00:00으로 매핑. 실제 DB 기준 4행."
  },
  {
    "id": "course_filter_12",
    "category": "course_filter",
    "query": "전자공학과 화요일 수업 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%전자공학과%' AND day_of_week = '화'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 22행."
  },
  {
    "id": "course_filter_13",
    "category": "course_filter",
    "query": "컴퓨터융합학부 전공(심화) 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND category LIKE '%전공(심화)%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 39행."
  },
  {
    "id": "course_filter_14",
    "category": "course_filter",
    "query": "컴퓨터융합학부 4학년 대상 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND target_year = 4",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 19행."
  },
  {
    "id": "course_filter_15",
    "category": "course_filter",
    "query": "간호학과 전공(기초) 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%간호학과%' AND category LIKE '%전공(기초)%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 8행."
  },
  {
    "id": "exclude_completed_courses_01",
    "category": "exclude_completed_courses",
    "query": "데이터베이스 관련 과목 중에서 내가 이미 들은 과목은 빼고 보여줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE subject_name LIKE '%데이터베이스%' AND NOT EXISTS (SELECT 1 FROM enrollment AS e WHERE e.student_id = '202102671' AND e.subject_code = v_course_info.subject_code)",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": true,
    "structural_checks": null,
    "notes": "제외 전 10행 -> 제외 후 2행(202102671은 1214-3033을 이미 수강)."
  },
  {
    "id": "exclude_completed_courses_02",
    "category": "exclude_completed_courses",
    "query": "알고리즘 과목 중에 내가 안 들은 것만 보여줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE subject_name LIKE '%알고리즘%' AND NOT EXISTS (SELECT 1 FROM enrollment AS e WHERE e.student_id = '202102671' AND e.subject_code = v_course_info.subject_code)",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": true,
    "structural_checks": null,
    "notes": "제외 전 5행 -> 제외 후 3행."
  },
  {
    "id": "exclude_completed_courses_03",
    "category": "exclude_completed_courses",
    "query": "컴퓨터융합학부 목요일 수업 중에 내가 이미 수강한 과목은 빼줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND day_of_week = '목' AND NOT EXISTS (SELECT 1 FROM enrollment AS e WHERE e.student_id = '202102671' AND e.subject_code = v_course_info.subject_code)",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": true,
    "structural_checks": null,
    "notes": "제외 전 16행 -> 제외 후 0행(학생이 목요일 CS 과목을 전부 수강함). 결과가 0행인 것 자체가 정답이며, 다른 exclude 케이스들이 0이 아닌 결과를 가지므로 채점기의 '항상 0행이면 통과' 편향 위험은 낮음."
  },
  {
    "id": "exclude_completed_courses_04",
    "category": "exclude_completed_courses",
    "query": "컴퓨터융합학부 2학년 대상 과목 중에서 내가 들은 거 빼고 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND target_year = 2 AND NOT EXISTS (SELECT 1 FROM enrollment AS e WHERE e.student_id = '202102671' AND e.subject_code = v_course_info.subject_code)",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": true,
    "structural_checks": null,
    "notes": "제외 전 30행 -> 제외 후 8행."
  },
  {
    "id": "exclude_completed_courses_05",
    "category": "exclude_completed_courses",
    "query": "컴퓨터융합학부 전공(심화) 과목 중 내가 아직 안 들은 것만 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT course_year, subject_code, section, subject_name, category, credit_hours, target_year, professor, capacity, enrolled, grading_method, eval_type, class_mode, dept_name, day_of_week, start_time, end_time, classroom, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND category LIKE '%전공(심화)%' AND NOT EXISTS (SELECT 1 FROM enrollment AS e WHERE e.student_id = '202102671' AND e.subject_code = v_course_info.subject_code)",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": true,
    "structural_checks": null,
    "notes": "제외 전 39행 -> 제외 후 7행."
  },
  {
    "id": "prerequisite_01",
    "category": "prerequisite",
    "query": "운영체제및실습 과목의 선수과목이 뭐야",
    "grading": "execution",
    "reference_sql": "SELECT subject_code, section, subject_name, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE subject_name LIKE '%운영체제및실습%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 6행, prereq_subject_names='자료구조'."
  },
  {
    "id": "prerequisite_02",
    "category": "prerequisite",
    "query": "선수과목으로 자료구조가 필요한 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT subject_code, section, subject_name, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE prereq_subject_names LIKE '%자료구조%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "필터 컬럼이 prereq_subject_names라는 점(과목명 자체가 아님)을 모델이 구분하는지 확인. 실제 DB 기준 24행."
  },
  {
    "id": "prerequisite_03",
    "category": "prerequisite",
    "query": "자료구조 과목의 선수과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT subject_code, section, subject_name, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE subject_name LIKE '%자료구조%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "'자료구조'와 '자료구조및실습'을 모두 포함하는 실제 DB 기준 16행."
  },
  {
    "id": "prerequisite_04",
    "category": "prerequisite",
    "query": "컴퓨터프로그래밍3 과목 선수과목이 뭐야",
    "grading": "execution",
    "reference_sql": "SELECT subject_code, section, subject_name, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE subject_name LIKE '%컴퓨터프로그래밍3%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 6행, prereq_subject_names='컴퓨터프로그래밍 1'."
  },
  {
    "id": "prerequisite_05",
    "category": "prerequisite",
    "query": "컴퓨터융합학부 과목 중에서 선수과목이 없는 과목 알려줘",
    "grading": "execution",
    "reference_sql": "SELECT subject_code, section, subject_name, prereq_subject_codes, prereq_subject_names FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND prereq_subject_names = '없음'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "'없음'은 NULL이 아니라 리터럴 문자열이다(prompt.py에 명시됨, 실제 DB로 확인됨). 실제 DB 기준 34행."
  },
  {
    "id": "enrollment_aggregate_01",
    "category": "enrollment_aggregate",
    "query": "컴퓨터융합학부에서 수강인원이 가장 많은 과목이 뭐야",
    "grading": "execution",
    "reference_sql": "SELECT subject_code, section, subject_name, enrolled, capacity FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' ORDER BY enrolled DESC LIMIT 1",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "실제 DB 기준 1행(subject_code=1190-2001, section=01, enrolled=79). 결과가 1행이라 order_sensitive는 의미가 없어 false로 둔다."
  },
  {
    "id": "enrollment_aggregate_02",
    "category": "enrollment_aggregate",
    "query": "컴퓨터융합학부 과목 중 정원이 다 찬 과목은 몇 개야",
    "grading": "execution",
    "reference_sql": "SELECT COUNT(DISTINCT subject_code || '-' || section) AS course_count FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND enrolled >= capacity AND capacity > 0",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "알려진 취약 케이스: v_course_info는 course_schedule/course_prerequisite와의 JOIN으로 행이 중복될 수 있다(course_filter_07은 raw 23행이지만 distinct 과목은 12개). 모델이 COUNT(*)를 그대로 쓰면 중복 집계로 오답 처리될 가능성이 높다 — 이는 프롬프트가 팬아웃을 안내하지 않는 실제 갭을 드러내기 위한 케이스다. 정답은 12."
  },
  {
    "id": "enrollment_aggregate_03",
    "category": "enrollment_aggregate",
    "query": "경제학과 전공핵심 과목은 총 몇 개 분반이야",
    "grading": "execution",
    "reference_sql": "SELECT COUNT(DISTINCT subject_code || '-' || section) AS course_count FROM v_course_info WHERE dept_name LIKE '%경제학과%' AND category LIKE '%전공(핵심)%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "enrollment_aggregate_02와 동일한 팬아웃 이슈. course_filter_06은 raw 27행, distinct는 17. 정답은 17."
  },
  {
    "id": "enrollment_aggregate_04",
    "category": "enrollment_aggregate",
    "query": "알고리즘 과목은 총 몇 개 분반이 있어",
    "grading": "execution",
    "reference_sql": "SELECT COUNT(DISTINCT subject_code || '-' || section) AS course_count FROM v_course_info WHERE subject_name LIKE '%알고리즘%'",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "course_filter_09는 raw 5행, distinct는 3. 정답은 3."
  },
  {
    "id": "enrollment_aggregate_05",
    "category": "enrollment_aggregate",
    "query": "컴퓨터융합학부 4학년 대상 과목은 몇 개야",
    "grading": "execution",
    "reference_sql": "SELECT COUNT(DISTINCT subject_code || '-' || section) AS course_count FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND target_year = 4",
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": null,
    "notes": "course_filter_14는 raw 19행, distinct는 11. 정답은 11."
  },
  {
    "id": "personalized_lookup_01",
    "category": "personalized_lookup",
    "query": "내 학과가 어디야",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": false,
    "structural_checks": {"required_tables": ["student"], "required_columns": [], "student_scoped": true},
    "notes": "알려진 파이프라인 갭: process.py는 exclude_completed_courses=True일 때만 student_id를 validate_sql의 requested_student_id로 전달한다(process.py의 validate_sql 호출부 참고). 즉 일반 개인화 조회에서는 SQL이 student.student_id = '202102671'로 스코프돼도 검증 시 플레이스홀더(:student_id 등)만 허용되어 실패할 가능성이 높다. 버그가 아니라 이 갭을 정량적으로 드러내기 위한 케이스."
  },
  {
    "id": "personalized_lookup_02",
    "category": "personalized_lookup",
    "query": "나 몇 학년이야",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": false,
    "structural_checks": {"required_tables": ["student"], "required_columns": ["student.grade"], "student_scoped": true},
    "notes": "personalized_lookup_01과 동일한 알려진 갭 적용."
  },
  {
    "id": "personalized_lookup_03",
    "category": "personalized_lookup",
    "query": "내 학번이랑 소속 학과 코드 알려줘",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": false,
    "structural_checks": {"required_tables": ["student"], "required_columns": ["student.student_id", "student.dept_code"], "student_scoped": true},
    "notes": "personalized_lookup_01과 동일한 알려진 갭 적용."
  },
  {
    "id": "personalized_lookup_04",
    "category": "personalized_lookup",
    "query": "내가 D094 소속 맞아?",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": false,
    "structural_checks": {"required_tables": ["student"], "required_columns": ["student.dept_code"], "student_scoped": true},
    "notes": "personalized_lookup_01과 동일한 알려진 갭 적용."
  },
  {
    "id": "personalized_lookup_05",
    "category": "personalized_lookup",
    "query": "내 정보 요약해서 보여줘",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": false,
    "structural_checks": {"required_tables": ["student"], "required_columns": [], "student_scoped": true},
    "notes": "personalized_lookup_01과 동일한 알려진 갭 적용. 질문이 열려있어 모델이 애초에 UNKNOWN을 반환할 수도 있음(그 경우 expects_error=false이므로 오답 처리됨 — 이 자체도 유의미한 측정치)."
  },
  {
    "id": "graduation_requirement_01",
    "category": "graduation_requirement",
    "query": "컴퓨터융합학부 학생이 꼭 들어야 하는 필수과목이 뭐야",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": {"required_tables": ["required_subject"], "required_columns": ["required_subject.subject_code"], "student_scoped": false},
    "notes": "required_subject 테이블은 현재 0행이라 실행 결과 비교는 무의미하다. SQL이 올바른 테이블/컬럼을 참조하는지만 검증한다."
  },
  {
    "id": "graduation_requirement_02",
    "category": "graduation_requirement",
    "query": "D094 학과 졸업 필수과목 알려줘",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": false,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": {"required_tables": ["required_subject"], "required_columns": ["required_subject.subject_code"], "student_scoped": false},
    "notes": "graduation_requirement_01과 동일한 사유."
  },
  {
    "id": "graduation_requirement_03",
    "category": "graduation_requirement",
    "query": "내가 졸업하려면 뭘 들어야 해",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": false,
    "student_id": "202102671",
    "exclude_completed_courses": false,
    "structural_checks": {"required_tables": ["student", "required_subject"], "required_columns": [], "student_scoped": true},
    "notes": "required_subject 데이터 부재 + personalized_lookup과 동일한 student 스코프 갭이 동시에 적용되는 케이스."
  },
  {
    "id": "ambiguous_reject_01",
    "category": "ambiguous_reject",
    "query": "오늘 날씨 어때?",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": true,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": {},
    "notes": "스키마와 완전히 무관한 질문. generate_sql이 UNKNOWN을 반환해 process()가 {\"error\": ...}를 돌려줘야 한다."
  },
  {
    "id": "ambiguous_reject_02",
    "category": "ambiguous_reject",
    "query": "다음 학기 수강신청은 언제 시작해?",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": true,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": {},
    "notes": "수강신청 일정은 스키마에 없는 정보. UNKNOWN 기대."
  },
  {
    "id": "ambiguous_reject_03",
    "category": "ambiguous_reject",
    "query": "학생들 이름이랑 전화번호 다 보여줘",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": true,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": {},
    "notes": "student.* 형태의 조회를 시도할 가능성이 높아 validate.py의 selects_student_data 검증(backend/validate.py:92)에 걸려야 한다. 또한 student 테이블에 전화번호 컬럼 자체가 없다."
  },
  {
    "id": "ambiguous_reject_04",
    "category": "ambiguous_reject",
    "query": "1학년 학생들 전체 명단을 보여줘",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": true,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": {},
    "notes": "특정 학생으로 스코프되지 않은 student 조회이므로 has_scoped_student_filter 검증에 걸려야 한다."
  },
  {
    "id": "ambiguous_reject_05",
    "category": "ambiguous_reject",
    "query": "데이터베이스 과목 정보를 삭제해줘",
    "grading": "structural",
    "reference_sql": null,
    "order_sensitive": false,
    "expects_error": true,
    "student_id": null,
    "exclude_completed_courses": false,
    "structural_checks": {},
    "notes": "DELETE 요청. validate.py의 BLOCKED_KEYWORDS 또는 SELECT-only 검증(backend/validate.py:24, 168)에 걸려야 한다."
  }
]
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest backend/eval/test_golden_queries.py -v`
Expected: 전체 PASS (6개)

- [ ] **Step 5: 커밋**

```bash
git add backend/eval/golden_queries.json backend/eval/test_golden_queries.py
git commit -m "data: add 43-case golden query set for text-to-sql evaluation"
```

---

### Task 5: CLI 실행기 (`run_eval.py`)

**Files:**
- Create: `backend/eval/run_eval.py`
- Create: `backend/eval/test_run_eval.py`

**Interfaces:**
- Consumes:
  - `backend.process.process(query: str, exclude_completed_courses: bool = False, student_id: str | None = None) -> dict` (기존 함수, `backend/process.py:418`)
  - `backend.eval.grading.grade_case(case: dict, result: dict) -> dict` (Task 3에서 구현)
- Produces:
  - `load_cases(path: Path) -> list[dict]`
  - `run_case(case: dict) -> dict` — `{"id", "category", "query", "ok", "reason", "sql", "reference_sql", "error"}`
  - `summarize(records: list[dict]) -> dict` — `{"overall": {...}, "by_category": {...}}`
  - `print_report(summary: dict, records: list[dict]) -> None`
  - `write_report_file(summary: dict, records: list[dict], report_dir: Path) -> Path`
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/eval/test_run_eval.py`:
```python
import json
from pathlib import Path

from backend.eval import run_eval


def test_load_cases_reads_json_array(tmp_path):
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps([{"id": "a"}]), encoding="utf-8")
    cases = run_eval.load_cases(cases_file)
    assert cases == [{"id": "a"}]


def test_run_case_calls_process_and_grades(monkeypatch):
    captured = {}

    def fake_process(query, exclude_completed_courses=False, student_id=None):
        captured["args"] = (query, exclude_completed_courses, student_id)
        return {"sql": "SELECT 1 LIMIT 50", "data": []}

    def fake_grade_case(case, result):
        return {"ok": True, "reason": None}

    monkeypatch.setattr(run_eval, "process", fake_process)
    monkeypatch.setattr(run_eval, "grade_case", fake_grade_case)

    case = {
        "id": "x",
        "category": "course_filter",
        "query": "테스트 질의",
        "student_id": "202102671",
        "exclude_completed_courses": True,
        "reference_sql": None,
    }
    record = run_eval.run_case(case)

    assert captured["args"] == ("테스트 질의", True, "202102671")
    assert record == {
        "id": "x",
        "category": "course_filter",
        "query": "테스트 질의",
        "ok": True,
        "reason": None,
        "sql": "SELECT 1 LIMIT 50",
        "reference_sql": None,
        "error": None,
    }


def test_run_case_records_exception_from_grading_without_crashing(monkeypatch):
    monkeypatch.setattr(run_eval, "process", lambda query, exclude_completed_courses=False, student_id=None: {"sql": "SELECT 1", "data": []})

    def failing_grade_case(case, result):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_eval, "grade_case", failing_grade_case)

    case = {"id": "x", "category": "course_filter", "query": "q", "reference_sql": None}
    record = run_eval.run_case(case)
    assert record["ok"] is False
    assert "boom" in record["reason"]


def test_summarize_computes_overall_and_per_category_accuracy():
    records = [
        {"category": "a", "ok": True},
        {"category": "a", "ok": False},
        {"category": "b", "ok": True},
    ]
    summary = run_eval.summarize(records)
    assert summary["overall"] == {"passed": 2, "total": 3, "accuracy": 66.7}
    assert summary["by_category"]["a"] == {"passed": 1, "total": 2, "accuracy": 50.0}
    assert summary["by_category"]["b"] == {"passed": 1, "total": 1, "accuracy": 100.0}


def test_write_report_file_creates_json_with_summary_and_records(tmp_path):
    summary = {"overall": {"passed": 1, "total": 1, "accuracy": 100.0}, "by_category": {}}
    records = [{"id": "x", "ok": True}]
    report_path = run_eval.write_report_file(summary, records, tmp_path)
    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["summary"] == summary
    assert saved["records"] == records


def test_main_returns_nonzero_when_below_min_accuracy(monkeypatch, tmp_path, capsys):
    cases = [
        {"id": "a", "category": "c", "query": "q1", "reference_sql": None},
        {"id": "b", "category": "c", "query": "q2", "reference_sql": None},
    ]
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")

    monkeypatch.setattr(run_eval, "GOLDEN_QUERIES_PATH", cases_file)
    monkeypatch.setattr(run_eval, "process", lambda query, exclude_completed_courses=False, student_id=None: {"sql": "SELECT 1", "data": []})

    call_count = {"n": 0}

    def fake_grade_case(case, result):
        call_count["n"] += 1
        return {"ok": call_count["n"] == 1, "reason": None if call_count["n"] == 1 else "실패"}

    monkeypatch.setattr(run_eval, "grade_case", fake_grade_case)

    exit_code = run_eval.main(["--report-dir", str(tmp_path / "reports"), "--min-accuracy", "80"])
    assert exit_code == 1

    exit_code_ok = run_eval.main(["--report-dir", str(tmp_path / "reports"), "--min-accuracy", "0"])
    assert exit_code_ok == 0


def test_main_filters_by_category(monkeypatch, tmp_path):
    cases = [
        {"id": "a", "category": "keep", "query": "q1", "reference_sql": None},
        {"id": "b", "category": "skip", "query": "q2", "reference_sql": None},
    ]
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")

    monkeypatch.setattr(run_eval, "GOLDEN_QUERIES_PATH", cases_file)

    seen_ids = []

    def fake_process(query, exclude_completed_courses=False, student_id=None):
        return {"sql": "SELECT 1", "data": []}

    def fake_grade_case(case, result):
        seen_ids.append(case["id"])
        return {"ok": True, "reason": None}

    monkeypatch.setattr(run_eval, "process", fake_process)
    monkeypatch.setattr(run_eval, "grade_case", fake_grade_case)

    run_eval.main(["--filter", "keep", "--report-dir", str(tmp_path / "reports")])
    assert seen_ids == ["a"]
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest backend/eval/test_run_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.eval.run_eval'`

- [ ] **Step 3: `run_eval.py` 구현**

`backend/eval/run_eval.py`:
```python
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..process import process
from .grading import grade_case

GOLDEN_QUERIES_PATH = Path(__file__).with_name("golden_queries.json")
DEFAULT_REPORTS_DIR = Path(__file__).with_name("reports")


def _ensure_utf8_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def load_cases(path: Path = GOLDEN_QUERIES_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def run_case(case: dict) -> dict:
    result = process(
        case["query"],
        exclude_completed_courses=case.get("exclude_completed_courses", False),
        student_id=case.get("student_id"),
    )
    try:
        grade = grade_case(case, result)
    except Exception as exc:
        grade = {"ok": False, "reason": f"채점 중 예외 발생: {exc}"}

    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "ok": grade["ok"],
        "reason": grade["reason"],
        "sql": result.get("sql"),
        "reference_sql": case.get("reference_sql"),
        "error": result.get("error"),
    }


def summarize(records: list[dict]) -> dict:
    by_category: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_category[record["category"]].append(record)

    category_summary = {}
    for category, items in sorted(by_category.items()):
        passed = sum(1 for item in items if item["ok"])
        category_summary[category] = {
            "passed": passed,
            "total": len(items),
            "accuracy": round(100 * passed / len(items), 1) if items else 0.0,
        }

    total_passed = sum(1 for record in records if record["ok"])
    total = len(records)
    overall_accuracy = round(100 * total_passed / total, 1) if total else 0.0

    return {
        "overall": {"passed": total_passed, "total": total, "accuracy": overall_accuracy},
        "by_category": category_summary,
    }


def print_report(summary: dict, records: list[dict]) -> None:
    print("=== 카테고리별 정확도 ===")
    for category, stats in summary["by_category"].items():
        print(f"{category:<28} {stats['passed']:>3}/{stats['total']:<3} ({stats['accuracy']}%)")
    print("-" * 55)
    overall = summary["overall"]
    print(f"{'전체':<28} {overall['passed']:>3}/{overall['total']:<3} ({overall['accuracy']}%)")

    failures = [record for record in records if not record["ok"]]
    if failures:
        print("\n=== 실패 케이스 ===")
        for record in failures:
            print(f"[{record['id']}] {record['query']}")
            print(f"  reason: {record['reason']}")
            print(f"  sql: {record['sql']}")
            if record.get("reference_sql"):
                print(f"  reference_sql: {record['reference_sql']}")
            if record.get("error"):
                print(f"  error: {record['error']}")


def write_report_file(summary: dict, records: list[dict], report_dir: Path) -> Path:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as file:
        json.dump({"summary": summary, "records": records}, file, ensure_ascii=False, indent=2)
    return report_path


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_console()
    parser = argparse.ArgumentParser(description="Text-to-SQL 골든 평가셋 실행기")
    parser.add_argument("--filter", default=None, help="이 문자열을 포함하는 category만 실행")
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=None,
        help="전체 정확도가 이 값(0-100) 미만이면 종료 코드 1",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORTS_DIR),
        help="JSON 리포트 저장 디렉터리",
    )
    args = parser.parse_args(argv)

    cases = load_cases(GOLDEN_QUERIES_PATH)
    if args.filter:
        cases = [case for case in cases if args.filter in case["category"]]

    if not cases:
        print("실행할 케이스가 없습니다.")
        return 1

    records = [run_case(case) for case in cases]
    summary = summarize(records)
    print_report(summary, records)

    report_path = write_report_file(summary, records, Path(args.report_dir))
    print(f"\n리포트 저장: {report_path}")

    if args.min_accuracy is not None and summary["overall"]["accuracy"] < args.min_accuracy:
        print(f"\n전체 정확도 {summary['overall']['accuracy']}% < 기준 {args.min_accuracy}% -> FAIL")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest backend/eval/test_run_eval.py -v`
Expected: 전체 PASS (7개)

- [ ] **Step 5: `backend/eval/reports/`가 git에 남지 않도록 처리**

저장소 루트의 `.gitignore`를 열어 다음 줄이 없으면 추가한다:
```
backend/eval/reports/
```

- [ ] **Step 6: 커밋**

```bash
git add backend/eval/run_eval.py backend/eval/test_run_eval.py .gitignore
git commit -m "feat: add CLI runner for text-to-sql golden evaluation set"
```

---

### Task 6: README + 실제 환경 검증 실행

**Files:**
- Create: `backend/eval/README.md`

**Interfaces:**
- Consumes: 없음 (문서 작업 + 수동 검증)

- [ ] **Step 1: `backend/eval/README.md` 작성**

```markdown
# Text-to-SQL 골든 평가셋

`backend/process.py`의 전체 파이프라인(NER 교정 → 벡터 캐시 조회 → LLM 생성 → 검증 → DB 실행 → 자기수정 재시도)을
실제 Postgres/Ollama에 대해 실행해 정확도를 측정하는 회귀 평가 도구다.

## 실행 방법

저장소 루트에서 (반드시 `backend/.env`에 `DATABASE_URL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`이 설정돼 있어야 함):

```bash
python -m backend.eval.run_eval
```

옵션:
- `--filter <문자열>`: category 이름에 이 문자열이 포함된 케이스만 실행 (예: `--filter course_filter`)
- `--min-accuracy <0-100>`: 전체 정확도가 이 값 미만이면 종료 코드 1 반환
- `--report-dir <경로>`: JSON 리포트 저장 위치 (기본값 `backend/eval/reports/`)

## 채점 방식

- `grading: "execution"` — `reference_sql`과 파이프라인이 생성한 SQL을 둘 다 실제 DB에 실행해 결과 행을
  순서 무관 집합으로 비교한다. 문법이 달라도 결과가 같으면 정답으로 처리한다.
- `grading: "structural"` — 실행 결과 비교가 부적절한 케이스(졸업요건처럼 데이터가 없거나, 학생이 1명뿐인
  개인화 조회)용. 생성된 SQL이 필요한 테이블/컬럼을 참조하는지, 학생 스코프가 걸렸는지만 검증한다.
- `expects_error: true` — 모호하거나 안전 정책상 거부돼야 하는 질의. `process()`가 `{"error": ...}`를
  반환해야 정답이다.

## 알려진 결과 해석 주의사항

이 평가셋을 처음 돌리면 다음 두 카테고리는 구조적으로 낮은 정확도가 나올 가능성이 높다. **채점기 버그가 아니다.**

1. **`personalized_lookup`, `graduation_requirement`의 일부 케이스**: `backend/process.py`는
   `exclude_completed_courses=True`일 때만 `student_id`를 SQL 검증의 `requested_student_id`로 전달한다.
   일반 개인화 조회(`exclude_completed_courses=False`)에서는 생성된 SQL이 올바르게
   `student.student_id = '202102671'`로 스코프돼도 검증 단계(`backend/validate.py`의
   `has_scoped_student_filter`)가 플레이스홀더(`:student_id` 등)만 허용하므로 거의 항상 실패한다.
   이는 이 평가셋이 처음으로 정량화한, 실제로 존재하는 파이프라인 갭이다.
2. **`enrollment_aggregate`의 개수 세기 케이스**: `v_course_info`는 `course_schedule`/`course_prerequisite`와의
   JOIN으로 같은 과목이 여러 행으로 중복될 수 있다. `prompt.py`가 이 사실을 모델에게 알려주지 않으므로,
   모델이 `COUNT(*)`를 그대로 쓰면 중복 집계로 오답이 된다.

이 두 가지는 이번 작업 범위에서 고치지 않는다(스펙 문서의 Out of scope 참고). 다음 반복에서 프롬프트/검증
로직을 수정할 때 우선순위를 정하는 데 이 평가셋의 카테고리별 정확도를 근거로 사용한다.

## 케이스 추가하기

`backend/eval/golden_queries.json`에 객체를 추가한다. 필수 키는
`backend/eval/test_golden_queries.py`의 `REQUIRED_KEYS`를 참고. 추가 후
`python -m pytest backend/eval/test_golden_queries.py`로 스키마를 검증한다.

`execution` 케이스를 추가할 때는 반드시 `reference_sql`을 실제 DB에 대해 직접 실행해 행 수가
의도한 대로 나오는지 확인한 뒤에 커밋한다(우연히 0행이 나오는 케이스는 채점 변별력이 없다).
```

- [ ] **Step 2: 전체 유닛 테스트 실행**

Run: `python -m pytest backend/eval/ -v`
Expected: 모든 테스트(Task 1~5에서 작성한 것 전부) PASS

- [ ] **Step 3: 실제 환경에서 전체 평가셋 실행 (수동 검증)**

Run: `python -m backend.eval.run_eval`

다음을 확인한다(자동화된 assert가 아니라 사람이 직접 판단):
- 콘솔에 카테고리별 정확도 표와 전체 정확도가 출력되는가
- `backend/eval/reports/`에 타임스탬프가 붙은 JSON 리포트 파일이 생성됐는가
- `course_filter`, `exclude_completed_courses`, `prerequisite` 카테고리 정확도가 0%나 100%처럼
  극단적이지 않은가 (극단값이면 채점 로직 자체의 버그 가능성을 의심하고 실패 케이스 3~5건을 수동으로
  `sql`/`reference_sql`을 눈으로 비교해 재현한다)
- README에 적은 "알려진 결과 해석 주의사항"대로 `personalized_lookup`/`graduation_requirement`/
  `enrollment_aggregate`가 낮게 나오는지 (예상과 다르게 전부 통과한다면 `check_structural`이나
  `run_query` 연결에 버그가 있다는 신호이므로 재확인한다)

- [ ] **Step 4: 커밋**

```bash
git add backend/eval/README.md
git commit -m "docs: add usage guide for text-to-sql golden evaluation set"
```

---

## Self-Review 결과

- **스펙 커버리지**: 채점 방식(execution/structural/expects_error) → Task 1~3, 골든 쿼리셋 포맷/카테고리/개수 → Task 4, 실행기 CLI(`--filter`, `--min-accuracy`, 리포트) → Task 5, README/수동 검증 → Task 6. 스펙의 모든 절이 태스크에 매핑됨.
- **플레이스홀더 스캔**: TBD/TODO/"적절히 처리" 표현 없음. 모든 코드/데이터가 완전한 내용으로 작성됨.
- **타입 일관성**: `grade_case`가 반환하는 `{"ok": bool, "reason": str | None}` 형태를 Task 3(정의)과 Task 5(`run_case`에서 소비)에서 동일하게 사용. `run_eval.GOLDEN_QUERIES_PATH`를 테스트에서 monkeypatch하는 방식도 Task 5 전체에서 일관됨.
