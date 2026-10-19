# Text-to-SQL 평가 체계 Implementation Plan (1단계 계획 A/3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 골든 평가셋을 43개에서 약 240개로 늘리고, 채점 왜곡(스케줄 확장·단일 컬럼 관대함·빈 정답)을 바로잡고, Soft-F1·실패 유형·응답 시간·단계 분리(decoupled) 평가를 갖춘 평가 실행기를 만든다.

**Architecture:** 기존 `backend/eval/`(grading.py, run_eval.py, golden_queries.json)를 확장한다. 채점 함수는 순수 함수로 유닛 테스트하고, 실행기는 파이프라인을 레지스트리(`PIPELINES`)로 주입받아 계획 B의 v2 파이프라인을 코드 변경 없이 끼울 수 있게 한다. 신규 `validate_golden.py`가 정답 SQL을 실제 DB에서 실행해 평가셋 품질을 검사한다.

**Tech Stack:** Python 3.10, pytest, psycopg2(기존 `backend/db.run_query`), sqlglot(기존 validate).

**Spec:** `docs/superpowers/specs/2026-10-19-text-to-sql-accuracy-design.md` (1장 평가 체계). 근거 자료: `docs/superpowers/research/2026-10-19-text-to-sql-literature-review.md`.

## 1단계 계획 로드맵

| # | 계획 | 내용 |
|---|---|---|
| **A** | **평가 체계 (이 문서)** | 채점 보강, 실행기 확장, 평가셋 ~240개 |
| B | v2 파이프라인 | 값 후보, 예시 저장소, M-Schema 프롬프트, 후보 생성·다수결·재시도, `PIPELINES["v2"]` 등록 |
| C | 모델 비교·선정 | 후보 모델 GGUF 준비, 확장 평가셋으로 비교·ablation, 선정 |

## Global Constraints

- 실행 규칙: 모든 명령은 저장소 루트(`D:\text-to-sql\TextToSQLProject`)에서, 테스트는 `python -m pytest backend/eval -q`. 테스트 import는 `from backend.eval import ...` / `from backend.eval.grading import ...`, 패키지 내부는 상대 import.
- 작업 브랜치: `feature/t2s-accuracy`. DB 접속 정보는 gitignore된 `backend/.env`(`DATABASE_URL`). DB는 **읽기만** 한다(SELECT만 실행).
- 실행 정확도(EX)는 기존 방식(결과 행을 순서 무관 집합으로 비교, 공통 컬럼 투영)을 유지하되 spec 1.2의 두 보정을 적용한다: ① 정답 SQL에도 `expand_schedule_filtered_course_rows` 적용 ② 정답 결과에 `subject_code`·`section`이 있으면 생성 결과에도 있어야 하고 비교 컬럼에 포함.
- 정답 결과가 0행인 케이스는 `"empty_gold": true`로 표시하고 헤드라인 정확도에서 제외해 별도 보고한다.
- 평가셋 목표 수: `course_filter` 80, `prerequisite` 30, `enrollment_aggregate` 35, `personalized_lookup` 30, `exclude_completed_courses` 30, `ambiguous_reject` 30, `graduation_requirement` 3(확장하지 않음 — 졸업요건은 이번 범위 밖) = **238**.
- 학생 케이스의 학번은 DB에 실제 이수 내역이 있는 `202102671`(공과대학 컴퓨터융합학부 D094, 2021학번)만 쓴다.
- 파이프라인 호출 규약(계획 B가 따른다): `pipeline(query: str, *, exclude_completed_courses: bool = False, student_id: str | None = None, value_hints: list[dict] | None = None) -> dict` — 반환 dict는 기존 `process()`와 같은 키(`sql`, `data`, `error` 등).
- 기존 파이프라인 코드(`process.py`, `prompt.py`, `llm.py` 등)는 이 계획에서 수정하지 않는다.
- 커밋 메시지: `feat:`/`fix:`/`test:`/`docs:` 접두사 + 영어 명령형, 끝에 작성 모델의 하네스가 지정한 `Co-Authored-By:` 줄.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `backend/eval/grading.py` (수정) | 정답 SQL 스케줄 확장, 식별 컬럼 규칙, `soft_f1`, `classify_failure` |
| `backend/eval/run_eval.py` (수정) | 파이프라인 레지스트리·decoupled 모드, 레코드 확장, 요약(빈 정답 분리, 실패 유형, p50/p95, Soft-F1), 리포트 config |
| `backend/eval/validate_golden.py` (신규) | 평가셋 품질 검사 CLI |
| `backend/eval/golden_queries.json` (수정) | 신규 필드(`gold_values`, `empty_gold`) + 케이스 확장 |
| `backend/eval/test_*.py` (수정/신규) | 위 각 모듈 테스트 |
| `backend/eval/README.md` (수정) | 새 기능·필드·작성 규칙 |

---

### Task 1: 채점 보강 (`grading.py`)

**Files:**
- Modify: `backend/eval/grading.py`
- Test: `backend/eval/test_grading.py`

**Interfaces:**
- Consumes: 기존 `common_columns`, `project_rows`, `compare_execution`, `grade_case`; `backend.process.expand_schedule_filtered_course_rows(sql) -> str`(지연 import)
- Produces:
  - `IDENTITY_COLUMNS = ("subject_code", "section")`
  - `compare_execution(reference_rows, generated_rows, order_sensitive=False) -> tuple[bool, str | None]` — 식별 컬럼 규칙 추가
  - `soft_f1(reference_rows, generated_rows) -> float` — 공통 컬럼 투영 후 행 다중집합 F1(0~1, 소수 4자리)
  - `expand_reference_sql(sql: str) -> str` — 정답 SQL에 스케줄 확장 적용(테스트에서 monkeypatch 가능)
  - `grade_case(case, result) -> dict` — execution 채점은 `{"ok", "reason", "soft_f1"}`, 그 외는 기존처럼 `{"ok", "reason"}`
  - `classify_failure(case, result, grade) -> str` — `"ok" | "reject_missed" | "error" | "structural_mismatch" | "empty_result" | "result_mismatch"`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/eval/test_grading.py` import 블록에 `soft_f1`, `classify_failure`를 추가하고 파일 끝에 추가:

```python
def test_compare_execution_requires_identity_columns_present_in_reference():
    reference_rows = [{"subject_code": "A", "section": "00", "subject_name": "자료구조"}]
    generated_rows = [{"subject_name": "자료구조"}]

    ok, reason = compare_execution(reference_rows, generated_rows)

    assert ok is False
    assert "subject_code" in reason and "section" in reason


def test_compare_execution_compares_on_identity_columns_when_present():
    reference_rows = [
        {"subject_code": "A", "section": "00", "subject_name": "자료구조"},
        {"subject_code": "B", "section": "00", "subject_name": "자료구조"},
    ]
    generated_rows = [{"subject_code": "A", "section": "00", "subject_name": "자료구조"}]

    ok, _ = compare_execution(reference_rows, generated_rows)

    assert ok is False


def test_compare_execution_without_identity_columns_keeps_intersection_behaviour():
    assert compare_execution([{"course_count": 3}], [{"course_count": 3, "x": 1}]) == (True, None)


def test_soft_f1_is_one_for_equal_sets_and_zero_for_disjoint():
    rows = [{"subject_code": "A", "section": "00"}, {"subject_code": "B", "section": "00"}]

    assert soft_f1(rows, list(reversed(rows))) == 1.0
    assert soft_f1(rows, [{"subject_code": "C", "section": "00"}]) == 0.0


def test_soft_f1_gives_partial_credit():
    reference_rows = [{"subject_code": c, "section": "00"} for c in ("A", "B", "C", "D")]
    generated_rows = [{"subject_code": c, "section": "00"} for c in ("A", "B")]

    assert soft_f1(reference_rows, generated_rows) == 0.6667


def test_soft_f1_edge_cases():
    assert soft_f1([], []) == 1.0
    assert soft_f1([{"a": 1}], []) == 0.0
    assert soft_f1([{"a": 1}], [{"b": 1}]) == 0.0


def test_grade_case_expands_reference_sql_and_reports_soft_f1(monkeypatch):
    calls = []
    monkeypatch.setattr(grading, "expand_reference_sql", lambda sql: sql + " /*expanded*/")

    def fake_run_query(sql):
        calls.append(sql)
        return [{"subject_code": "A", "section": "00"}]

    monkeypatch.setattr(grading, "run_query", fake_run_query)
    case = {"id": "x", "grading": "execution", "reference_sql": "SELECT subject_code, section FROM v_course_info"}
    result = {"sql": "SELECT 1", "data": [{"subject_code": "A", "section": "00"}]}

    grade = grade_case(case, result)

    assert calls == ["SELECT subject_code, section FROM v_course_info /*expanded*/"]
    assert grade == {"ok": True, "reason": None, "soft_f1": 1.0}


@pytest.mark.parametrize("case, result, grade, expected", [
    ({"grading": "execution"}, {"data": [1]}, {"ok": True}, "ok"),
    ({"expects_error": True, "grading": "structural"}, {"sql": "SELECT 1"}, {"ok": False}, "reject_missed"),
    ({"grading": "execution"}, {"error": "UNKNOWN"}, {"ok": False}, "error"),
    ({"grading": "structural"}, {"sql": "SELECT 1"}, {"ok": False}, "structural_mismatch"),
    ({"grading": "execution"}, {"sql": "SELECT 1", "data": []}, {"ok": False}, "empty_result"),
    ({"grading": "execution"}, {"sql": "SELECT 1", "data": [{"a": 1}]}, {"ok": False}, "result_mismatch"),
])
def test_classify_failure(case, result, grade, expected):
    assert classify_failure(case, result, grade) == expected
```

파일 상단 import에 `import pytest`와 `from backend.eval import grading`이 없으면 추가한다.

기존 `test_grade_case_execution_uses_run_query_for_reference_sql`은 새 동작에 맞게 수정한다: 함수 첫 줄에 `monkeypatch.setattr(grading, "expand_reference_sql", lambda sql: sql)`를 추가하고, 마지막 단언을 `assert grade == {"ok": True, "reason": None, "soft_f1": 1.0}`로 바꾼다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest backend/eval/test_grading.py -q`
Expected: FAIL — `ImportError: cannot import name 'soft_f1'`

- [ ] **Step 3: 구현**

`backend/eval/grading.py`에서 import 줄에 `from collections import Counter`를 추가하고, `compare_execution` 바로 위에 상수와 헬퍼를, 아래에 새 함수들을 둔다.

```python
IDENTITY_COLUMNS = ("subject_code", "section")


def _missing_identity_columns(reference_rows: list[dict], generated_rows: list[dict]) -> list[str]:
    reference_keys = set(reference_rows[0].keys())
    generated_keys = set(generated_rows[0].keys())
    return [
        column for column in IDENTITY_COLUMNS
        if column in reference_keys and column not in generated_keys
    ]
```

`compare_execution`에서 `columns = common_columns(...)` 바로 앞(양쪽 모두 비어 있지 않음이 확인된 뒤)에 추가:

```python
    missing_identity = _missing_identity_columns(reference_rows, generated_rows)
    if missing_identity:
        return False, f"생성 결과에 식별 컬럼이 없습니다: {', '.join(missing_identity)}"
```

새 함수:

```python
def soft_f1(reference_rows: list[dict], generated_rows: list[dict]) -> float:
    """Row-level F1 over the common columns (a simplified BIRD Soft-F1)."""
    if not reference_rows and not generated_rows:
        return 1.0
    if not reference_rows or not generated_rows:
        return 0.0
    columns = common_columns(reference_rows, generated_rows)
    if not columns:
        return 0.0
    reference = Counter(project_rows(reference_rows, columns))
    generated = Counter(project_rows(generated_rows, columns))
    true_positive = sum((reference & generated).values())
    if true_positive == 0:
        return 0.0
    precision = true_positive / sum(generated.values())
    recall = true_positive / sum(reference.values())
    return round(2 * precision * recall / (precision + recall), 4)


def expand_reference_sql(sql: str) -> str:
    # Imported lazily: process.py pulls in the NER model and the vector cache.
    from ..process import expand_schedule_filtered_course_rows

    return expand_schedule_filtered_course_rows(sql)


def classify_failure(case: dict, result: dict, grade: dict) -> str:
    if grade.get("ok"):
        return "ok"
    if case.get("expects_error"):
        return "reject_missed"
    if isinstance(result, dict) and result.get("error"):
        return "error"
    if case.get("grading") == "structural":
        return "structural_mismatch"
    if not (result or {}).get("data"):
        return "empty_result"
    return "result_mismatch"
```

`grade_case`의 execution 분기를 교체:

```python
    if case["grading"] == "execution":
        reference_rows = run_query(expand_reference_sql(case["reference_sql"]))
        generated_rows = result.get("data", [])
        ok, reason = compare_execution(reference_rows, generated_rows, case.get("order_sensitive", False))
        return {"ok": ok, "reason": reason, "soft_f1": soft_f1(reference_rows, generated_rows)}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest backend/eval/test_grading.py -q`
Expected: 전부 통과 (기존 테스트 + 신규 13개; parametrize 6건 포함)

- [ ] **Step 5: 커밋**

```bash
git add backend/eval/grading.py backend/eval/test_grading.py
git commit -m "feat: grade against expanded references, require identity columns, add soft-F1 and failure types"
```

---

### Task 2: 실행기 확장 (`run_eval.py`)

**Files:**
- Modify: `backend/eval/run_eval.py`
- Test: `backend/eval/test_run_eval.py`

**Interfaces:**
- Consumes: `grade_case`, `classify_failure` (Task 1); 기존 `process`
- Produces (계획 B·C가 사용):
  - `v1_pipeline(query, *, exclude_completed_courses=False, student_id=None, value_hints=None) -> dict` — 모듈 전역 `process`를 호출 시점에 조회(monkeypatch 가능), `value_hints` 무시
  - `PIPELINES: dict[str, Callable]` = `{"v1": v1_pipeline}` — 계획 B가 `"v2"`를 등록
  - `run_case(case, pipeline=None, decoupled=False) -> dict` — 레코드 키: 기존 8개 + `failure_type`, `latency_ms`(int), `soft_f1`(float|None), `empty_gold`(bool)
  - `percentile(values: list[float], p: float) -> float | None` — nearest-rank
  - `summarize(records) -> dict` — `overall`·`by_category`는 `empty_gold` 제외, 추가 키 `empty_gold`, `failure_types`, `latency_ms`(`p50`,`p95`), `mean_soft_f1`
  - `collect_config(pipeline_name, decoupled) -> dict` — `{"pipeline", "decoupled", "env": {T2S_*, OLLAMA_MODEL 값}}`
  - `write_report_file(summary, records, report_dir, config=None) -> Path`
  - CLI: `--pipeline {v1,...}`(기본 v1), `--decoupled`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/eval/test_run_eval.py`의 `test_run_case_calls_process_and_grades`를 아래로 교체:

```python
def test_run_case_calls_process_and_grades(monkeypatch):
    captured = {}

    def fake_process(query, exclude_completed_courses=False, student_id=None):
        captured["args"] = (query, exclude_completed_courses, student_id)
        return {"sql": "SELECT 1 LIMIT 50", "data": [{"a": 1}]}

    monkeypatch.setattr(run_eval, "process", fake_process)
    monkeypatch.setattr(run_eval, "grade_case", lambda case, result: {"ok": True, "reason": None, "soft_f1": 1.0})

    case = {
        "id": "x",
        "category": "course_filter",
        "query": "테스트 질의",
        "grading": "execution",
        "student_id": "202102671",
        "exclude_completed_courses": True,
        "reference_sql": None,
    }
    record = run_eval.run_case(case)

    assert captured["args"] == ("테스트 질의", True, "202102671")
    latency = record.pop("latency_ms")
    assert isinstance(latency, int) and latency >= 0
    assert record == {
        "id": "x",
        "category": "course_filter",
        "query": "테스트 질의",
        "ok": True,
        "reason": None,
        "sql": "SELECT 1 LIMIT 50",
        "reference_sql": None,
        "error": None,
        "failure_type": "ok",
        "soft_f1": 1.0,
        "empty_gold": False,
    }
```

파일 끝에 추가:

```python
def test_run_case_passes_gold_values_only_in_decoupled_mode(monkeypatch):
    seen = []

    def pipeline(query, *, exclude_completed_courses=False, student_id=None, value_hints=None):
        seen.append(value_hints)
        return {"sql": "SELECT 1", "data": []}

    monkeypatch.setattr(run_eval, "grade_case", lambda case, result: {"ok": False, "reason": "x"})
    gold = [{"column": "dept_name", "value": "공과대학 컴퓨터융합학부"}]
    case = {"id": "x", "category": "c", "query": "q", "grading": "execution", "gold_values": gold}

    run_eval.run_case(case, pipeline=pipeline)
    run_eval.run_case(case, pipeline=pipeline, decoupled=True)

    assert seen == [None, gold]


def test_run_case_records_pipeline_exception_as_failure():
    def broken(query, **kwargs):
        raise RuntimeError("ollama down")

    record = run_eval.run_case({"id": "x", "category": "c", "query": "q", "grading": "execution"}, pipeline=broken)

    assert record["ok"] is False
    assert record["failure_type"] == "exception"
    assert "ollama down" in record["reason"]


def test_percentile_nearest_rank():
    values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]

    assert run_eval.percentile(values, 50) == 500
    assert run_eval.percentile(values, 95) == 1000
    assert run_eval.percentile([], 50) is None


def _record(category, ok, failure_type="ok", latency=100, f1=None, empty=False):
    return {"category": category, "ok": ok, "failure_type": failure_type,
            "latency_ms": latency, "soft_f1": f1, "empty_gold": empty}


def test_summarize_separates_empty_gold_and_reports_extras():
    records = [
        _record("a", True, latency=100, f1=1.0),
        _record("a", False, "result_mismatch", latency=300, f1=0.5),
        _record("b", True, latency=200),
        _record("b", True, latency=900, empty=True),
    ]

    summary = run_eval.summarize(records)

    assert summary["overall"] == {"passed": 2, "total": 3, "accuracy": 66.7}
    assert summary["by_category"]["b"] == {"passed": 1, "total": 1, "accuracy": 100.0}
    assert summary["empty_gold"] == {"passed": 1, "total": 1}
    assert summary["failure_types"] == {"ok": 3, "result_mismatch": 1}
    assert summary["latency_ms"] == {"p50": 200, "p95": 900}
    assert summary["mean_soft_f1"] == 0.75


def test_collect_config_snapshots_t2s_environment(monkeypatch):
    monkeypatch.setenv("T2S_CANDIDATES", "5")
    monkeypatch.setenv("OLLAMA_MODEL", "m")

    config = run_eval.collect_config("v1", True)

    assert config["pipeline"] == "v1"
    assert config["decoupled"] is True
    assert config["env"]["T2S_CANDIDATES"] == "5"
    assert config["env"]["OLLAMA_MODEL"] == "m"


def test_write_report_file_includes_config(tmp_path):
    path = run_eval.write_report_file({"overall": {}}, [], tmp_path, config={"pipeline": "v1"})

    assert json.loads(path.read_text(encoding="utf-8"))["config"] == {"pipeline": "v1"}


def test_main_rejects_unknown_pipeline(capsys):
    with pytest.raises(SystemExit):
        run_eval.main(["--pipeline", "nope"])
```

상단에 `import pytest`가 없으면 추가한다. 기존 `test_run_case_records_exception_from_grading_without_crashing`은 그대로 통과해야 한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest backend/eval/test_run_eval.py -q`
Expected: FAIL — `AttributeError`(`percentile`, `collect_config` 등 없음) 및 레코드 키 불일치

- [ ] **Step 3: 구현**

`backend/eval/run_eval.py` 수정:

import에 `import math`, `import os`, `import time`, `from typing import Callable`을 추가하고 `from .grading import grade_case`를 `from .grading import classify_failure, grade_case`로 바꾼다.

`load_cases` 아래에 추가:

```python
def v1_pipeline(query, *, exclude_completed_courses=False, student_id=None, value_hints=None):
    # value_hints is ignored: v1 has no hint input. Looks up `process` at call time.
    return process(query, exclude_completed_courses=exclude_completed_courses, student_id=student_id)


PIPELINES: dict[str, Callable] = {"v1": v1_pipeline}
```

`_case_record`를 교체:

```python
def _case_record(case: dict, ok: bool, reason: str | None, sql=None, error=None,
                 failure_type: str = "ok", latency_ms: int = 0, soft_f1=None) -> dict:
    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "ok": ok,
        "reason": reason,
        "sql": sql,
        "reference_sql": case.get("reference_sql"),
        "error": error,
        "failure_type": failure_type,
        "latency_ms": latency_ms,
        "soft_f1": soft_f1,
        "empty_gold": bool(case.get("empty_gold", False)),
    }
```

`run_case`를 교체:

```python
def run_case(case: dict, pipeline: Callable | None = None, decoupled: bool = False) -> dict:
    pipeline = pipeline or PIPELINES["v1"]
    hints = case.get("gold_values") if decoupled else None
    started = time.perf_counter()
    try:
        result = pipeline(
            case["query"],
            exclude_completed_courses=case.get("exclude_completed_courses", False),
            student_id=case.get("student_id"),
            value_hints=hints,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _case_record(case, ok=False, reason=f"파이프라인 실행 중 예외 발생: {exc}",
                            failure_type="exception", latency_ms=latency_ms)
    latency_ms = int((time.perf_counter() - started) * 1000)

    warning = result.get("warning") if isinstance(result, dict) else None
    if isinstance(warning, str) and warning.startswith("DATABASE_URL is not set"):
        return _case_record(
            case, ok=False,
            reason=f"DATABASE_URL이 설정되지 않아 SQL-only 모드로 동작했습니다: {warning}",
            sql=result.get("sql"), failure_type="exception", latency_ms=latency_ms,
        )

    try:
        grade = grade_case(case, result)
    except Exception as exc:
        grade = {"ok": False, "reason": f"채점 중 예외 발생: {exc}"}

    return _case_record(
        case,
        ok=grade["ok"],
        reason=grade["reason"],
        sql=result.get("sql"),
        error=result.get("error"),
        failure_type=classify_failure(case, result, grade),
        latency_ms=latency_ms,
        soft_f1=grade.get("soft_f1"),
    )
```

`summarize` 위에 추가하고 `summarize`를 교체:

```python
def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(p / 100 * len(ordered)) - 1)
    return ordered[index]


def _accuracy(items: list[dict]) -> dict:
    passed = sum(1 for item in items if item["ok"])
    return {
        "passed": passed,
        "total": len(items),
        "accuracy": round(100 * passed / len(items), 1) if items else 0.0,
    }


def summarize(records: list[dict]) -> dict:
    scored = [record for record in records if not record.get("empty_gold")]
    empty = [record for record in records if record.get("empty_gold")]

    by_category: dict[str, list[dict]] = defaultdict(list)
    for record in scored:
        by_category[record["category"]].append(record)

    failure_types: dict[str, int] = defaultdict(int)
    for record in records:
        failure_types[record.get("failure_type", "ok")] += 1

    latencies = [record["latency_ms"] for record in records if record.get("latency_ms") is not None]
    f1_values = [record["soft_f1"] for record in records if record.get("soft_f1") is not None]

    return {
        "overall": _accuracy(scored),
        "by_category": {category: _accuracy(items) for category, items in sorted(by_category.items())},
        "empty_gold": {"passed": sum(1 for r in empty if r["ok"]), "total": len(empty)},
        "failure_types": dict(sorted(failure_types.items())),
        "latency_ms": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95)},
        "mean_soft_f1": round(sum(f1_values) / len(f1_values), 4) if f1_values else None,
    }


def collect_config(pipeline_name: str, decoupled: bool) -> dict:
    env = {key: value for key, value in sorted(os.environ.items()) if key.startswith("T2S_")}
    if "OLLAMA_MODEL" in os.environ:
        env["OLLAMA_MODEL"] = os.environ["OLLAMA_MODEL"]
    return {"pipeline": pipeline_name, "decoupled": decoupled, "env": env}
```

`print_report`의 전체 줄 다음에 추가:

```python
    print(f"{'빈 정답(별도)':<28} {summary['empty_gold']['passed']:>3}/{summary['empty_gold']['total']:<3}")
    print(f"실패 유형: {summary['failure_types']}")
    print(f"응답 시간 p50={summary['latency_ms']['p50']}ms p95={summary['latency_ms']['p95']}ms")
    print(f"평균 Soft-F1: {summary['mean_soft_f1']}")
```

`write_report_file`에 `config: dict | None = None` 인자를 추가하고 저장 dict를 `{"config": config or {}, "summary": summary, "records": records}`로 바꾼다.

`main`의 parser에 추가:

```python
    parser.add_argument("--pipeline", default="v1", choices=sorted(PIPELINES), help="평가할 파이프라인")
    parser.add_argument("--decoupled", action="store_true", help="정답 값 힌트(gold_values)를 주입해 생성 단계만 평가")
```

`records = [run_case(case) for case in cases]`를 `records = [run_case(case, PIPELINES[args.pipeline], args.decoupled) for case in cases]`로, `write_report_file(...)` 호출에 `config=collect_config(args.pipeline, args.decoupled)`를 넘긴다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest backend/eval/test_run_eval.py -q`
Expected: 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add backend/eval/run_eval.py backend/eval/test_run_eval.py
git commit -m "feat: pluggable pipelines, decoupled mode, latency and failure-type reporting in the eval runner"
```

---

### Task 3: 평가셋 품질 검사 (`validate_golden.py`)

**Files:**
- Create: `backend/eval/validate_golden.py`
- Test: `backend/eval/test_validate_golden.py`
- Modify: `backend/eval/test_golden_queries.py` (43개 고정 단언 제거, 신규 필드 형식 검사)

**Interfaces:**
- Consumes: `backend.db.run_query`, `expand_reference_sql` (Task 1), `load_cases` (기존)
- Produces:
  - `MAX_ROWS = 500`
  - `check_cases(cases: list[dict], run=run_query, expand=expand_reference_sql) -> tuple[list[str], list[str]]` — (problems, warnings)
  - CLI `python -m backend.eval.validate_golden` — problems가 있으면 종료 코드 1, 카테고리별 개수 출력

검사 규칙:
1. `id` 중복 → problem
2. `query` 문자열 완전 중복 → problem
3. `gold_values`가 있으면 `[{"column": str, "value": str}, ...]` 형식 → 아니면 problem
4. execution 케이스: `expand(reference_sql)`를 실행. 예외 → problem. 0행인데 `empty_gold`가 아님 → problem. 1행 이상인데 `empty_gold: true` → problem. `MAX_ROWS` 초과 → warning
5. `expects_error: true`가 아닌 학생 케이스(`student_id` 존재)의 학번이 `202102671`이 아니면 → problem

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/eval/test_validate_golden.py`:

```python
from backend.eval.validate_golden import MAX_ROWS, check_cases


def case(**overrides):
    base = {
        "id": "c1", "category": "course_filter", "query": "q1", "grading": "execution",
        "reference_sql": "SELECT 1", "expects_error": False, "student_id": None,
    }
    base.update(overrides)
    return base


def identity(sql):
    return sql


def rows(n):
    return lambda sql: [{"a": i} for i in range(n)]


def test_clean_case_has_no_problems():
    assert check_cases([case()], run=rows(3), expand=identity) == ([], [])


def test_duplicate_ids_and_queries_are_problems():
    problems, _ = check_cases([case(), case(query="q2"), case(id="c3")], run=rows(1), expand=identity)

    assert any("id 중복" in p and "c1" in p for p in problems)
    assert any("질의 중복" in p and "q1" in p for p in problems)


def test_empty_reference_requires_empty_gold_flag():
    problems, _ = check_cases([case()], run=rows(0), expand=identity)
    assert any("0행" in p for p in problems)

    assert check_cases([case(empty_gold=True)], run=rows(0), expand=identity) == ([], [])

    problems, _ = check_cases([case(empty_gold=True)], run=rows(2), expand=identity)
    assert any("empty_gold" in p for p in problems)


def test_reference_sql_is_expanded_before_running():
    seen = []

    def run(sql):
        seen.append(sql)
        return [{"a": 1}]

    check_cases([case()], run=run, expand=lambda sql: sql + " X")

    assert seen == ["SELECT 1 X"]


def test_failing_reference_sql_is_a_problem():
    def run(sql):
        raise RuntimeError("syntax error")

    problems, _ = check_cases([case()], run=run, expand=identity)

    assert any("syntax error" in p for p in problems)


def test_too_many_rows_is_a_warning():
    problems, warnings = check_cases([case()], run=rows(MAX_ROWS + 1), expand=identity)

    assert problems == []
    assert any(str(MAX_ROWS + 1) in w for w in warnings)


def test_gold_values_format_is_checked():
    good = case(gold_values=[{"column": "dept_name", "value": "공과대학 컴퓨터융합학부"}])
    bad = case(id="c2", query="q2", gold_values=[{"column": "dept_name"}])

    problems, _ = check_cases([good, bad], run=rows(1), expand=identity)

    assert len(problems) == 1 and "c2" in problems[0]


def test_student_cases_must_use_the_known_student():
    problems, _ = check_cases([case(student_id="209999999")], run=rows(1), expand=identity)

    assert any("202102671" in p for p in problems)


def test_structural_cases_are_not_executed():
    def run(sql):
        raise AssertionError("must not run")

    assert check_cases([case(grading="structural", reference_sql=None)], run=run, expand=identity) == ([], [])
```

`backend/eval/test_golden_queries.py`에서 `test_golden_queries_file_has_43_cases`와 `test_category_counts_match_design`을 삭제하고 아래를 추가:

```python
def test_optional_fields_have_valid_types():
    for case in _load_cases():
        if "empty_gold" in case:
            assert isinstance(case["empty_gold"], bool), case["id"]
        if "gold_values" in case:
            assert isinstance(case["gold_values"], list), case["id"]
            for item in case["gold_values"]:
                assert set(item) == {"column", "value"}, case["id"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest backend/eval/test_validate_golden.py backend/eval/test_golden_queries.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.eval.validate_golden'`

- [ ] **Step 3: 구현**

`backend/eval/validate_golden.py`:

```python
"""Check the golden set: reference SQL runs, empty results are flagged, fields are well-formed.

Usage: python -m backend.eval.validate_golden
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from ..db import run_query
from .grading import expand_reference_sql
from .run_eval import GOLDEN_QUERIES_PATH, load_cases

MAX_ROWS = 500
KNOWN_STUDENT_ID = "202102671"


def _gold_values_ok(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and set(item) == {"column", "value"}
        and isinstance(item["column"], str)
        and isinstance(item["value"], str)
        for item in value
    )


def check_cases(cases: list[dict], run=run_query, expand=expand_reference_sql) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []

    for case_id, count in Counter(case["id"] for case in cases).items():
        if count > 1:
            problems.append(f"id 중복: {case_id} ({count}회)")
    for query, count in Counter(case["query"] for case in cases).items():
        if count > 1:
            problems.append(f"질의 중복: {query} ({count}회)")

    for case in cases:
        case_id = case["id"]
        if "gold_values" in case and not _gold_values_ok(case["gold_values"]):
            problems.append(f"{case_id}: gold_values 형식 오류")
        if case.get("student_id") and not case.get("expects_error") and case["student_id"] != KNOWN_STUDENT_ID:
            problems.append(f"{case_id}: 학생 케이스는 학번 {KNOWN_STUDENT_ID}만 사용")
        if case.get("grading") != "execution":
            continue
        try:
            row_count = len(run(expand(case["reference_sql"])))
        except Exception as exc:
            problems.append(f"{case_id}: reference_sql 실행 실패: {exc}")
            continue
        if row_count == 0 and not case.get("empty_gold"):
            problems.append(f"{case_id}: 정답 결과가 0행인데 empty_gold가 아님")
        if row_count > 0 and case.get("empty_gold"):
            problems.append(f"{case_id}: empty_gold인데 정답 결과가 {row_count}행")
        if row_count > MAX_ROWS:
            warnings.append(f"{case_id}: 정답 결과가 {row_count}행 (> {MAX_ROWS})")

    return problems, warnings


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cases = load_cases(GOLDEN_QUERIES_PATH)
    problems, warnings = check_cases(cases)

    counts = Counter(case["category"] for case in cases)
    print(f"케이스 {len(cases)}개")
    for category, count in sorted(counts.items()):
        print(f"  {category:<28} {count}")
    for warning in warnings:
        print(f"WARN  {warning}")
    for problem in problems:
        print(f"ERROR {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest backend/eval -q`
Expected: 전부 통과

- [ ] **Step 5: 기존 43개에 적용하고 데이터 보정**

Run: `python -m backend.eval.validate_golden`
Expected: `exclude_completed_courses_03`이 "0행인데 empty_gold가 아님"으로 보고된다(2026-10-19 확인: 확장 전후 0행). 이 케이스에 `"empty_gold": true`를 추가한다. 다른 problem이 나오면 해당 케이스의 `reference_sql`을 실제 DB로 확인해 고친다(고친 내용은 `notes`에 한 줄 기록). 다시 실행해 종료 코드 0을 확인한다.

- [ ] **Step 6: 커밋**

```bash
git add backend/eval/validate_golden.py backend/eval/test_validate_golden.py backend/eval/test_golden_queries.py backend/eval/golden_queries.json
git commit -m "feat: validate the golden set against the database and flag empty-gold cases"
```

---

### Task 4: 평가셋 확장 — `course_filter` (15 → 80)

**Files:**
- Modify: `backend/eval/golden_queries.json`

**Interfaces:**
- Consumes: `validate_golden` CLI (Task 3)
- Produces: 케이스 `course_filter_16` ~ `course_filter_80`

작성 규칙 (Task 4~7 공통 — 다른 태스크 브리프에도 똑같이 들어 있다):
1. **형식**: 기존 케이스와 같은 키 전체(`id, category, query, grading, reference_sql, order_sensitive, expects_error, student_id, exclude_completed_courses, structural_checks, notes`) + `gold_values`. id는 카테고리 내 다음 번호부터 두 자리(`course_filter_16`).
2. **gold_values**: 질의가 가리키는 DB 값을 `{"column": "<v_course_info 컬럼>", "value": "<DB 실제 값>"}`으로 모두 적는다(예: "컴융" → `{"column": "dept_name", "value": "공과대학 컴퓨터융합학부"}`). 값은 반드시 `SELECT DISTINCT <컬럼> FROM v_course_info`로 확인한 실제 문자열.
3. **reference_sql 관례**: 과목 검색은 `course_filter_01`과 같은 20개 컬럼 SELECT, 학과·과목명은 `LIKE '%값%'`, 요일은 `day_of_week = '목'`, 시간은 `start_time = 'HH:MM:SS'`(범위 질의만 비교 연산), 대상 학년은 `target_year`, 과목 수는 `COUNT(DISTINCT subject_code || '-' || section) AS course_count`. 요일·시간 필터는 그대로 쓰면 채점 시 스케줄 확장이 자동 적용된다.
4. **한국어 다양성**: 새 케이스 중 최소 40%는 변형 표현 — 약어(컴융, 전핵, 전기, 교필), 구어체("~있어?", "~좀"), 조사 생략, 띄어쓰기 오류, 어순 변경. 같은 정답 SQL을 공유하는 질의는 최대 3개.
5. **난이도 분포**: 조건 1개 30%, 2개 40%, 3개 이상 30%. 조건 종류를 고르게 섞는다(학과, 이수구분, 요일, 시간·오전/오후, 대상 학년, 학점, 교수, 강의방식, 정원·여석).
6. **검증**: 정답 결과는 1~500행. 추가할 때마다 `python -m backend.eval.validate_golden`이 problem 0으로 끝나야 한다. `notes`에 "실제 DB 기준 N행"을 적는다.
7. **금지**: 존재하지 않는 값, 시점에 따라 바뀌는 표현("이번 주"), 정답이 해석에 따라 갈리는 질의(그런 질의는 `ambiguous_reject`로).

- [ ] **Step 1: DB 값 목록 확인**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "from dotenv import load_dotenv; load_dotenv('backend/.env'); from backend.db import run_query as q; [print(c, [r[c] for r in q(f'SELECT DISTINCT {c} FROM v_course_info ORDER BY 1 LIMIT 60')]) for c in ('dept_name','category','day_of_week','class_mode','grading_method','eval_type','credit_hours','target_year')]"
```
출력을 작성 기준으로 삼는다.

- [ ] **Step 2: 케이스 65개 작성**

`course_filter_16`부터 `course_filter_80`까지 위 규칙대로 작성해 `golden_queries.json`의 `course_filter` 케이스 뒤에 넣는다. 작성하면서 10개 단위로 `python -m backend.eval.validate_golden`을 실행한다.

- [ ] **Step 3: 검증**

Run: `python -m backend.eval.validate_golden && python -m pytest backend/eval -q`
Expected: problem 0, `course_filter` 80개, 테스트 전부 통과

- [ ] **Step 4: 커밋**

```bash
git add backend/eval/golden_queries.json
git commit -m "test: expand course_filter golden cases to 80"
```

---

### Task 5: 평가셋 확장 — `prerequisite` (5 → 30), `enrollment_aggregate` (5 → 35)

**Files:**
- Modify: `backend/eval/golden_queries.json`

**Interfaces:**
- Consumes: `validate_golden` CLI (Task 3)
- Produces: `prerequisite_06`~`prerequisite_30`, `enrollment_aggregate_06`~`enrollment_aggregate_35`

작성 규칙: Task 4의 1~7번 규칙을 그대로 따른다(1. 기존 키 전체 + `gold_values`, 두 자리 id / 2. gold_values는 DB 실제 값 / 3. reference_sql 관례 / 4. 40% 이상 변형 표현, 같은 정답 SQL 최대 3개 / 5. 조건 수 분포 30·40·30 / 6. 1~500행, validate_golden problem 0, notes에 행 수 / 7. 없는 값·시점 표현·해석이 갈리는 질의 금지). 추가 규칙:
- `prerequisite`: 선수과목 조회(`prereq_subject_names`/`prereq_subject_codes`), "선수과목 없는 과목"(`prereq_subject_names = '없음'`), 특정 과목을 선수로 요구하는 과목 역조회(`prereq_subject_names LIKE '%자료구조%'`), 학과·이수구분 조건과의 결합을 섞는다.
- `enrollment_aggregate`: 개수(`COUNT(DISTINCT subject_code || '-' || section) AS course_count`), 최대·최소(`ORDER BY ... LIMIT 1` — 동점이 있으면 정답이 갈리므로 `notes`에 동점 없음을 확인해 적는다), 여석(`capacity - enrolled`), 정원 초과·마감(`enrolled >= capacity AND capacity > 0`), 학과·이수구분별 집계(`GROUP BY`)를 섞는다. `ORDER BY`가 결과 의미에 필요한 경우만 `order_sensitive: true`.

- [ ] **Step 1: 케이스 작성** — 위 규칙대로 55개를 작성해 각 카테고리 뒤에 넣는다. 10개마다 `python -m backend.eval.validate_golden`.
- [ ] **Step 2: 검증** — Run: `python -m backend.eval.validate_golden && python -m pytest backend/eval -q` / Expected: problem 0, 두 카테고리 30·35개, 테스트 통과
- [ ] **Step 3: 커밋**

```bash
git add backend/eval/golden_queries.json
git commit -m "test: expand prerequisite and aggregate golden cases"
```

---

### Task 6: 평가셋 확장 — `personalized_lookup` (5 → 30), `exclude_completed_courses` (5 → 30)

**Files:**
- Modify: `backend/eval/golden_queries.json`

**Interfaces:**
- Consumes: `validate_golden` CLI (Task 3)
- Produces: `personalized_lookup_01`~`_30`(기존 5개 개정 포함), `exclude_completed_courses_06`~`_30`

작성 규칙: Task 4의 1~7번 규칙을 그대로 따른다(1. 기존 키 전체 + `gold_values`, 두 자리 id / 2. gold_values는 DB 실제 값 / 3. reference_sql 관례 / 4. 40% 이상 변형 표현, 같은 정답 SQL 최대 3개 / 5. 조건 수 분포 30·40·30 / 6. 1~500행, validate_golden problem 0, notes에 행 수 / 7. 없는 값·시점 표현·해석이 갈리는 질의 금지). 추가 규칙:
- 모든 케이스 `student_id: "202102671"`.
- **`personalized_lookup`은 execution 채점으로 전환한다**(spec 3.2: v2는 학번을 파라미터로 바인딩하므로 실행 결과 비교가 가능). 기존 5개를 포함해 전부 `grading: "execution"`, `structural_checks: null`, `reference_sql`은 학번 리터럴 `'202102671'` 사용. 범위: 내 학과·학년·학번(`student`), 내가 들은 과목 목록·학점·성적·연도별(`enrollment` + `subject` 조인), 내 학과 개설 과목(`student.dept_code` → `department.dept_name` → `v_course_info.dept_name`). 기존 notes의 structural 관련 설명은 "2026-10-19 execution 채점으로 전환" 한 줄로 바꾼다.
- `exclude_completed_courses`: `exclude_completed_courses: true`, 기존 `exclude_completed_courses_01`과 같은 `NOT EXISTS (SELECT 1 FROM enrollment AS e WHERE e.student_id = '202102671' AND e.subject_code = v_course_info.subject_code)` 패턴. 제외 전후 행 수를 `notes`에 적는다(제외로 실제 행이 줄어드는 케이스가 절반 이상).
- `student`의 개인 식별 컬럼은 허용 목록(`validate.py`의 `ALLOWED_STUDENT_COLUMNS`: admission_year, completed_credits, dept_code, grade, student_id) 안에서만 쓴다.

- [ ] **Step 1: 케이스 작성·개정** — 위 규칙대로 개정 5개 + 신규 50개. 10개마다 `python -m backend.eval.validate_golden`.
- [ ] **Step 2: 검증** — Run: `python -m backend.eval.validate_golden && python -m pytest backend/eval -q` / Expected: problem 0, 두 카테고리 각 30개, `personalized_lookup`에 structural 케이스 0개, 테스트 통과
- [ ] **Step 3: 커밋**

```bash
git add backend/eval/golden_queries.json
git commit -m "test: expand student-scoped golden cases and grade personalized lookups by execution"
```

---

### Task 7: 평가셋 확장 — `ambiguous_reject` (5 → 30), 목표 수 고정, README

**Files:**
- Modify: `backend/eval/golden_queries.json`, `backend/eval/test_golden_queries.py`, `backend/eval/README.md`

**Interfaces:**
- Consumes: Task 1~6 결과
- Produces: `ambiguous_reject_06`~`_30`, 목표 수 테스트, README 개정

작성 규칙: Task 4의 1·4·7번(형식, 변형 표현, 금지 사항)을 따른다. 추가 규칙:
- `grading: "structural"`, `expects_error: true`, `reference_sql: null`, `structural_checks: {}`, `gold_values: []`.
- 유형을 고르게: 스키마에 없는 정보(수강신청 일정, 강의평, 교수 연락처), 다른 학생·전체 학생 개인정보, 쓰기 요청(삭제·수정·추가), 지시 대명사만 있는 질의("그거 몇 시야?"), 서비스와 무관한 질의.

- [ ] **Step 1: 케이스 25개 작성** 후 `python -m backend.eval.validate_golden`.

- [ ] **Step 2: 목표 수 테스트 추가** — `backend/eval/test_golden_queries.py` 끝에:

```python
def test_category_counts_match_the_expanded_design():
    counts: dict[str, int] = {}
    for case in _load_cases():
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {
        "course_filter": 80,
        "prerequisite": 30,
        "enrollment_aggregate": 35,
        "personalized_lookup": 30,
        "exclude_completed_courses": 30,
        "ambiguous_reject": 30,
        "graduation_requirement": 3,
    }


def test_non_reject_cases_carry_gold_values():
    for case in _load_cases():
        if not case["expects_error"] and case["category"] != "graduation_requirement":
            assert "gold_values" in case, case["id"]
```

- [ ] **Step 3: 기존 케이스에 gold_values 보강** — `course_filter_01~15`, `prerequisite_01~05`, `enrollment_aggregate_01~05`, `exclude_completed_courses_01~05`에 `gold_values`가 없으면 Task 4 규칙 2대로 채운다(값이 없는 질의는 `[]`).

- [ ] **Step 4: README 개정** — `backend/eval/README.md`에 반영: 실행 옵션 `--pipeline`, `--decoupled`; 리포트 신규 항목(빈 정답 분리, 실패 유형, p50/p95, Soft-F1, config); 채점 보정 두 가지(스케줄 확장 적용, 식별 컬럼 규칙)와 "알려진 결과 해석 주의사항" 3·4번이 이것으로 해소됨; 신규 필드 `gold_values`·`empty_gold`; `validate_golden` 사용법; Task 4 작성 규칙 1~7을 "케이스 추가하기"에 옮겨 적기.

- [ ] **Step 5: 검증**

Run: `python -m backend.eval.validate_golden && python -m pytest backend/eval -q`
Expected: problem 0, 케이스 238개, 테스트 전부 통과

- [ ] **Step 6: 커밋**

```bash
git add backend/eval/golden_queries.json backend/eval/test_golden_queries.py backend/eval/README.md
git commit -m "test: expand reject cases, pin the 238-case design and document the eval system"
```

---

### Task 8 (수동, 사용자): 평가셋 검토와 v1 기준선 측정

서브에이전트에 맡기지 않는다.

- [ ] **Step 1:** 사용자가 카테고리별 무작위 10개씩 검토한다(질의가 자연스러운지, 정답 SQL이 의도와 맞는지). 고칠 케이스는 목록으로 전달 → 수정 후 `validate_golden` 재확인.
- [ ] **Step 2:** v1 기준선 측정(Ollama·DB 필요): `python -m backend.eval.run_eval --pipeline v1` 과 `python -m backend.eval.run_eval --pipeline v1 --decoupled`. 두 리포트 경로를 계획 B·C의 비교 기준으로 기록한다.
