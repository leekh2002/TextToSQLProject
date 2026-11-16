# Text-to-SQL v2 파이프라인 Implementation Plan (1단계 계획 B/3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M-Schema 프롬프트·값 후보·예시 검색·후보 5개 생성·실행 결과 다수결·출력 컬럼 정규화를 갖춘 v2 파이프라인(`backend/t2s/`)을 만들어 평가 실행기(`PIPELINES["v2"]`)와 API(`T2S_PIPELINE=v2`)에 연결한다.

**Architecture:** `backend/t2s/` 패키지에 책임별 모듈을 둔다: `config`(환경변수 설정) → `postprocess`(출력 컬럼 정규화·LIMIT) → `schema_doc`(M-Schema) → `values`(값 후보) → `examples`(검증된 예시 저장소) → `prompt`(채팅 메시지) → `generate`(Ollama 후보 생성) → `execute`(후보별 검증·변환·실행) → `vote`(다수결) → `pipeline`(조립). LLM·DB·임베딩·NER은 모두 주입 가능한 의존성으로 두어 DB/LLM 없이 유닛 테스트한다. 기존 v1 경로(`process.py`)는 수정하지 않고, 그 안의 실행 전 변환 함수만 재사용한다.

**Tech Stack:** Python 3.10, sqlglot 30.8(설치됨), rapidfuzz, numpy, psycopg2, PyYAML 6.0.2(설치됨 — requirements에 추가), Ollama `/api/chat`, KURE-v1(기존 `vector_cache.embed_text`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-19-text-to-sql-accuracy-design.md` (3장 파이프라인, 3.4 출력 정규화, 4장 프롬프트, 5장 구조, 부록 "계획 B로 넘기는 사항"). 근거: `docs/superpowers/research/2026-10-19-text-to-sql-literature-review.md`.

## Global Constraints

- 저장소 루트에서 실행, 테스트는 `python -m pytest backend/t2s backend/eval backend/test_validate_student.py backend/test_validate_security.py -q`. 테스트 import는 `from backend.t2s.xxx import ...`, 패키지 내부는 상대 import. PYTHONIOENCODING=utf-8.
- 작업 브랜치 `feature/t2s-accuracy`. DB는 읽기 전용. `backend/process.py`, `backend/llm.py`, `backend/prompt.py`, `backend/keyword_extract.py`는 수정하지 않는다(함수 재사용만). `backend/validate.py`는 Task 8의 이동 외에는 수정하지 않는다.
- 파이프라인 계약(평가 실행기와 API가 의존): `run_v2(query, *, exclude_completed_courses=False, student_id=None, value_hints=None) -> dict`, `run_v2.accepts_value_hints = True`. 반환 키: `sql`, `data`, `error`, `rejected`(bool), `cache_hit`(False), `candidates`(후보 메타 목록), `timings_ms`, `query`. 거부 시 `{"error": "질문이 모호합니다.", "rejected": True, "data": [], "sql": None, ...}`.
- `value_hints`: `None`이면 파이프라인이 직접 값 후보를 찾고, 리스트(빈 리스트 포함)면 그것만 쓴다. 각 원소는 `{"column": str, "value": str}`.
- 학번은 SQL에 `%(student_id)s`로 쓰고 실행 시 파라미터로 바인딩한다. 바인딩할 때 SQL의 다른 `%`는 `%%`로 이스케이프한다. 이수 과목 제외(`exclude_completed_courses=True`)는 기존 `process.exclude_completed_courses_sql(sql, student_id)`(학번 리터럴)로 파이프라인이 붙인다.
- 출력 컬럼 정규화(spec 3.4): 집계·GROUP BY·HAVING·윈도우·DISTINCT ON·조인이 없는 단일 `v_course_info` SELECT만 표준 20개 컬럼(`STANDARD_COLUMNS`)으로 바꾸고, 원래 SELECT의 별칭이 있는 비표준 계산 컬럼은 뒤에 남긴다. 스케줄 확장은 이 "강의 목록 질의"에만 적용한다.
- 설정은 환경변수(호출 시점에 읽음): `T2S_MODEL`(기본 `OLLAMA_MODEL`), `T2S_CANDIDATES`=5, `T2S_TEMPERATURE`=0.7, `T2S_EXAMPLES_K`=4, `T2S_USE_EXAMPLES`=1, `T2S_VALUE_SOURCES`=`ner,ngram`, `T2S_ROW_CAP`=50, `T2S_STATEMENT_TIMEOUT_MS`=3000, `T2S_REVIEW_LOG`=1.
- 예시 검색은 원문 질문의 KURE 유사도 기준이며, SQL 골격이 겹치지 않게 k개를 고른다(마스킹 질문 병합은 생략 — NER 오류 전파를 피함). 정확 일치 즉시 응답 경로는 두지 않는다(spec 개정).
- 예시 저장소(`backend/t2s/data/examples.json`)는 평가셋과 겹치면 안 된다: 평가셋 질의와 KURE 유사도 0.9 이상이거나 정답 SQL이 동일한 예시는 금지.
- 커밋 메시지는 `feat:`/`fix:`/`test:`/`docs:` + 영어 명령형, 끝에 작성 모델 하네스의 `Co-Authored-By:` 줄.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `backend/eval/grading.py` (수정) | 50행 상한 규칙 보완(중복 행 금지, 잘린 결과의 컬럼 값 매칭) |
| `backend/t2s/__init__.py`, `config.py` | 패키지, 설정 |
| `backend/t2s/postprocess.py` | 강의 목록 질의 판별, 출력 컬럼 정규화, LIMIT 보장 |
| `backend/t2s/schema_docs.yaml`, `schema_doc.py` | 한국어 컬럼 설명 + DB 값으로 M-Schema 생성 |
| `backend/t2s/values.py` | 값 후보(NER + n-gram) |
| `backend/t2s/examples.py`, `data/examples.json` | 검증된 예시 저장소, 오염 검사·승인 CLI |
| `backend/t2s/prompt.py` | 시스템 지시·규칙·스키마·값 후보·예시 → 채팅 메시지 |
| `backend/t2s/generate.py` | Ollama `/api/chat`, SQL 추출, 후보 병렬 생성 |
| `backend/validate.py` (이동만) | `is_safety_rejection` (run_eval의 거부 판정 이동) |
| `backend/t2s/execute.py` | 후보별 검증 → 변환 → 바인딩 → 실행 |
| `backend/t2s/vote.py` | 결과 서명, 다수결 |
| `backend/t2s/pipeline.py` | 조립, 재시도, 응답, 검토 로그 |
| `backend/eval/run_eval.py`, `backend/main.py` (수정) | v2 등록, API 전환 |

---

### Task 1: 50행 상한 채점 보완 (계획 A 보류 항목)

**Files:** Modify `backend/eval/grading.py`; Test `backend/eval/test_grading.py`

**Interfaces:** Produces 동일 시그니처의 `compare_execution`, `match_columns(reference_rows, generated_rows)` — 동작만 보완.

규칙:
1. 상한 통과 규칙은 생성 결과가 정확히 `row_cap()`행이고 **중복 행이 없을 때만**(`len(set(generated_projection)) == len(generated_projection)`) 적용한다.
2. 이름이 다른 컬럼의 값 매칭: 생성 결과가 정확히 `row_cap()`행이면 값 다중집합 일치 대신 "생성 값 집합 ⊆ 정답 값 집합"으로 매칭하되, 그런 후보 컬럼이 둘 이상이면 매칭하지 않는다.

- [ ] **Step 1: 실패하는 테스트**

`backend/eval/test_grading.py` 끝에 추가:

```python
def test_capped_result_with_duplicate_rows_does_not_pass(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "3")
    reference = [{"subject_code": c, "section": "00"} for c in "ABCDE"]
    generated = [{"subject_code": "A", "section": "00"}] * 3

    ok, _ = compare_execution(reference, generated)

    assert ok is False


def test_capped_distinct_subset_still_passes(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "3")
    reference = [{"subject_code": c, "section": "00"} for c in "ABCDE"]
    generated = [{"subject_code": c, "section": "00"} for c in "ABC"]

    assert compare_execution(reference, generated) == (True, None)


def test_capped_renamed_column_matches_by_value_subset(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "2")
    reference = [{"course_count": n} for n in (1, 2, 3)]
    generated = [{"cnt": n} for n in (1, 2)]

    assert compare_execution(reference, generated) == (True, None)


def test_capped_renamed_column_is_not_matched_when_ambiguous(monkeypatch):
    monkeypatch.setenv("T2S_ROW_CAP", "2")
    reference = [{"course_count": n} for n in (1, 2, 3)]
    generated = [{"a": 1, "b": 1}, {"a": 2, "b": 2}]

    ok, reason = compare_execution(reference, generated)

    assert ok is False and "course_count" in reason
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest backend/eval/test_grading.py -q` / Expected: 신규 4개 중 2개 이상 FAIL(중복 행 통과, 상한 하위집합 값 매칭).

- [ ] **Step 3: 구현** — `match_columns`의 값 매칭 루프를 교체:

```python
    capped = len(generated_rows) == row_cap()
    for column in reference_columns:
        if column in matched:
            continue
        reference_values = _column_values(reference_rows, column)
        if capped:
            reference_set = set(reference_values)
            candidates = [
                candidate for candidate in generated_columns
                if candidate not in used and set(_column_values(generated_rows, candidate)) <= reference_set
            ]
            if len(candidates) == 1:
                matched[column] = candidates[0]
                used.add(candidates[0])
            continue
        for candidate in generated_columns:
            if candidate in used:
                continue
            if _column_values(generated_rows, candidate) == reference_values:
                matched[column] = candidate
                used.add(candidate)
                break
```

`compare_execution`의 상한 분기를 교체:

```python
    cap = row_cap()
    if len(generated_rows) == cap and len(set(generated_projection)) == len(generated_projection):
        if order_sensitive:
            if generated_projection == reference_projection[:cap]:
                return True, None
        elif set(generated_projection) <= set(reference_projection):
            return True, None
```

- [ ] **Step 4: 통과 확인** — Run: `python -m pytest backend/eval -q` / Expected: 전부 통과.
- [ ] **Step 5: 커밋** — `git add backend/eval/grading.py backend/eval/test_grading.py && git commit -m "fix: require distinct rows and subset value matching for capped results"`

---

### Task 2: 설정과 출력 정규화 (`config.py`, `postprocess.py`)

**Files:** Create `backend/t2s/__init__.py`(빈 파일), `backend/t2s/config.py`, `backend/t2s/postprocess.py`, `backend/t2s/tests/__init__.py`(빈 파일); Test `backend/t2s/tests/test_config.py`, `backend/t2s/tests/test_postprocess.py`

**Interfaces:**
- `config.Settings` frozen dataclass: `model: str, candidates: int, temperature: float, examples_k: int, use_examples: bool, value_sources: tuple[str, ...], row_cap: int, statement_timeout_ms: int, review_log: bool`; `config.load_settings() -> Settings`
- `postprocess.STANDARD_COLUMNS: tuple[str, ...]`(20개, 순서 고정)
- `postprocess.is_course_row_query(sql: str) -> bool`
- `postprocess.normalize_projection(sql: str) -> str`
- `postprocess.ensure_limit(sql: str, cap: int) -> str`

- [ ] **Step 1: 실패하는 테스트**

`backend/t2s/tests/test_config.py`:

```python
from backend.t2s.config import load_settings


def test_defaults(monkeypatch):
    for key in ("T2S_MODEL", "T2S_CANDIDATES", "T2S_TEMPERATURE", "T2S_EXAMPLES_K", "T2S_USE_EXAMPLES",
                "T2S_VALUE_SOURCES", "T2S_ROW_CAP", "T2S_STATEMENT_TIMEOUT_MS", "T2S_REVIEW_LOG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "base-m")

    s = load_settings()

    assert (s.model, s.candidates, s.temperature, s.examples_k) == ("base-m", 5, 0.7, 4)
    assert s.use_examples is True and s.review_log is True
    assert s.value_sources == ("ner", "ngram")
    assert (s.row_cap, s.statement_timeout_ms) == (50, 3000)


def test_overrides(monkeypatch):
    monkeypatch.setenv("T2S_MODEL", "x")
    monkeypatch.setenv("T2S_CANDIDATES", "1")
    monkeypatch.setenv("T2S_USE_EXAMPLES", "0")
    monkeypatch.setenv("T2S_VALUE_SOURCES", "ngram")
    monkeypatch.setenv("T2S_REVIEW_LOG", "0")

    s = load_settings()

    assert (s.model, s.candidates, s.use_examples, s.value_sources, s.review_log) == ("x", 1, False, ("ngram",), False)
```

`backend/t2s/tests/test_postprocess.py`:

```python
import pytest

from backend.t2s.postprocess import STANDARD_COLUMNS, ensure_limit, is_course_row_query, normalize_projection


def test_standard_columns_are_the_twenty_course_columns():
    assert len(STANDARD_COLUMNS) == 20
    assert STANDARD_COLUMNS[:3] == ("course_year", "subject_code", "section")


@pytest.mark.parametrize("sql, expected", [
    ("SELECT subject_name FROM v_course_info WHERE dept_name LIKE '%컴%' LIMIT 50", True),
    ("SELECT c.subject_name FROM v_course_info AS c WHERE c.day_of_week = '목'", True),
    ("SELECT COUNT(*) FROM v_course_info", False),
    ("SELECT dept_name, COUNT(*) FROM v_course_info GROUP BY dept_name", False),
    ("SELECT s.grade FROM student s WHERE s.student_id = '1'", False),
    ("SELECT c.subject_name FROM v_course_info c JOIN department d ON c.dept_name = d.dept_name", False),
    ("SELECT subject_name, rank() OVER (ORDER BY enrolled) FROM v_course_info", False),
    ("SELECT subject_name FROM v_course_info UNION SELECT subject_name FROM subject", False),
    ("not sql at all", False),
])
def test_is_course_row_query(sql, expected):
    assert is_course_row_query(sql) is expected


def test_normalize_projection_uses_standard_columns_with_alias():
    sql = normalize_projection("SELECT c.subject_name FROM v_course_info AS c WHERE c.day_of_week = '목' LIMIT 50")

    assert sql.startswith("SELECT c.course_year, c.subject_code, c.section")
    assert "c.prereq_subject_names FROM v_course_info AS c WHERE c.day_of_week = '목' LIMIT 50" in sql


def test_normalize_projection_keeps_aliased_computed_columns_for_order_by():
    sql = normalize_projection(
        "SELECT subject_name, capacity - enrolled AS remain FROM v_course_info ORDER BY remain DESC LIMIT 5"
    )

    assert "prereq_subject_names, capacity - enrolled AS remain FROM v_course_info ORDER BY remain DESC LIMIT 5" in sql


def test_normalize_projection_drops_distinct_and_star():
    sql = normalize_projection("SELECT DISTINCT * FROM v_course_info WHERE target_year = 3")

    assert sql.startswith("SELECT v_course_info.course_year")
    assert "DISTINCT" not in sql


def test_normalize_projection_leaves_other_queries_untouched():
    sql = "SELECT COUNT(DISTINCT subject_code || '-' || section) AS course_count FROM v_course_info"

    assert normalize_projection(sql) == sql


def test_ensure_limit_adds_only_when_missing():
    assert ensure_limit("SELECT 1 FROM v_course_info", 50) == "SELECT 1 FROM v_course_info LIMIT 50"
    assert ensure_limit("SELECT 1 FROM v_course_info LIMIT 5", 50) == "SELECT 1 FROM v_course_info LIMIT 5"
    assert ensure_limit("garbage (", 50) == "garbage ("
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest backend/t2s -q` / Expected: `ModuleNotFoundError: No module named 'backend.t2s'`

- [ ] **Step 3: 구현**

`backend/t2s/config.py`:

```python
"""v2 pipeline settings, read from the environment at call time (eval ablations flip them)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    model: str
    candidates: int
    temperature: float
    examples_k: int
    use_examples: bool
    value_sources: tuple[str, ...]
    row_cap: int
    statement_timeout_ms: int
    review_log: bool


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", ""}


def load_settings() -> Settings:
    sources = os.getenv("T2S_VALUE_SOURCES", "ner,ngram")
    return Settings(
        model=os.getenv("T2S_MODEL") or os.getenv("OLLAMA_MODEL", ""),
        candidates=int(os.getenv("T2S_CANDIDATES", "5")),
        temperature=float(os.getenv("T2S_TEMPERATURE", "0.7")),
        examples_k=int(os.getenv("T2S_EXAMPLES_K", "4")),
        use_examples=_flag("T2S_USE_EXAMPLES", "1"),
        value_sources=tuple(s.strip() for s in sources.split(",") if s.strip()),
        row_cap=int(os.getenv("T2S_ROW_CAP", "50")),
        statement_timeout_ms=int(os.getenv("T2S_STATEMENT_TIMEOUT_MS", "3000")),
        review_log=_flag("T2S_REVIEW_LOG", "1"),
    )
```

`backend/t2s/postprocess.py`:

```python
"""Deterministic SQL rewrites applied before execution (spec 3.4)."""
from __future__ import annotations

import sqlglot
from sqlglot import exp

STANDARD_COLUMNS = (
    "course_year", "subject_code", "section", "subject_name", "category", "credit_hours",
    "target_year", "professor", "capacity", "enrolled", "grading_method", "eval_type",
    "class_mode", "dept_name", "day_of_week", "start_time", "end_time", "classroom",
    "prereq_subject_codes", "prereq_subject_names",
)


def _parse(sql: str):
    try:
        return sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return None


def _course_source_alias(tree) -> str | None:
    if not isinstance(tree, exp.Select) or tree.args.get("joins"):
        return None
    source = tree.args.get("from_")
    table = source.this if source is not None else None
    if not isinstance(table, exp.Table) or table.name.lower() != "v_course_info":
        return None
    return table.alias_or_name


def is_course_row_query(sql: str) -> bool:
    tree = _parse(sql)
    if tree is None or _course_source_alias(tree) is None:
        return False
    if tree.args.get("group") or tree.args.get("having"):
        return False
    if tree.find(exp.AggFunc) or tree.find(exp.Window):
        return False
    distinct = tree.args.get("distinct")
    return not (distinct is not None and distinct.args.get("on"))


def normalize_projection(sql: str) -> str:
    if not is_course_row_query(sql):
        return sql
    tree = _parse(sql)
    alias = _course_source_alias(tree)
    extras = [
        expression for expression in tree.expressions
        if isinstance(expression, exp.Alias) and expression.alias not in STANDARD_COLUMNS
    ]
    tree.set("expressions", [exp.column(column, table=alias) for column in STANDARD_COLUMNS] + extras)
    tree.set("distinct", None)
    return tree.sql(dialect="postgres")


def ensure_limit(sql: str, cap: int) -> str:
    tree = _parse(sql)
    if tree is None or not isinstance(tree, (exp.Select, exp.SetOperation)):
        return sql
    if tree.args.get("limit") is not None:
        return sql
    return tree.limit(cap).sql(dialect="postgres")
```

- [ ] **Step 4: 통과 확인** — Run: `python -m pytest backend/t2s -q` / Expected: 전부 통과. 문자열 단언이 sqlglot 출력 형식(예: `AS c` 유지, 공백)과 다르면 **기대 문자열이 아니라** sqlglot의 실제 출력에 맞는 형태로 단언을 고치되, 의미(표준 컬럼 순서, 별칭, 별칭 계산 컬럼 유지, DISTINCT 제거)는 그대로 검증하고 보고서에 적는다.
- [ ] **Step 5: 커밋** — `feat: add v2 settings and course-row projection normalization`

---

### Task 3: M-Schema (`schema_docs.yaml`, `schema_doc.py`)

**Files:** Create `backend/t2s/schema_docs.yaml`, `backend/t2s/schema_doc.py`; Modify `backend/requirements.txt`(`pyyaml` 추가); Test `backend/t2s/tests/test_schema_doc.py`

**Interfaces:**
- `schema_doc.load_column_docs(path=DOCS_PATH) -> dict` — YAML 그대로
- `schema_doc.build_mschema(docs: dict, fetch) -> str` — `fetch(sql, params=None) -> list[dict]`(기본 `backend.db.run_query`)
- `schema_doc.get_mschema() -> str` — `functools.lru_cache` 1회 생성

YAML 형식: `tables: [{name, description, columns: [{name, type, description, values: auto|none}]}]`, 선택 `foreign_keys: ["enrollment.student_id → student.student_id", ...]`. `values: auto`면 DB의 DISTINCT 값 수가 20 이하일 때 전체 값, 아니면 예시 3개(빈도 상위). `values: none`이면 값을 넣지 않는다(학생 개인정보).

출력 형식(테스트가 고정):
```
# Table: v_course_info (강의 개설 정보. 한 과목·분반이 요일·시간 수만큼 여러 행)
[
(course_year: INTEGER, 교과목 편성 학년, Values: [1, 2, 3, 4, 5]),
(dept_name: VARCHAR, 개설 학과, Examples: ['공과대학 컴퓨터융합학부', ...]),
...
]
【Foreign keys】
enrollment.student_id → student.student_id
```

- [ ] **Step 1: YAML 작성** — `backend/t2s/schema_docs.yaml`:

```yaml
tables:
  - name: v_course_info
    description: 강의 개설 정보. 한 과목·분반이 요일·시간 수만큼 여러 행으로 나온다
    columns:
      - {name: course_year, type: INTEGER, description: 교과목 편성 학년(질문의 대상 학년에는 쓰지 않음), values: auto}
      - {name: subject_code, type: VARCHAR, description: 교과목 코드, values: auto}
      - {name: section, type: VARCHAR, description: 분반 번호(문자열), values: auto}
      - {name: subject_name, type: VARCHAR, description: 과목명, values: auto}
      - {name: category, type: VARCHAR, description: 이수구분(전공핵심=전공(핵심) 등 괄호 표기), values: auto}
      - {name: credit_hours, type: VARCHAR, description: "학점/이론/실습 (예: '3/3/0', 학점 조건은 LIKE '3/%')", values: auto}
      - {name: target_year, type: INTEGER, description: 수강 대상 학년(질문의 'N학년 대상/N학년 과목'), values: auto}
      - {name: professor, type: VARCHAR, description: 담당 교수, values: auto}
      - {name: capacity, type: INTEGER, description: 정원, values: none}
      - {name: enrolled, type: INTEGER, description: 수강 신청 인원, values: none}
      - {name: grading_method, type: VARCHAR, description: 성적 산출 방식, values: auto}
      - {name: eval_type, type: VARCHAR, description: 평가 유형(상대평가/절대평가), values: auto}
      - {name: class_mode, type: VARCHAR, description: 수업 방식, values: auto}
      - {name: dept_name, type: VARCHAR, description: 개설 학과(대학명 포함 전체 이름), values: auto}
      - {name: day_of_week, type: VARCHAR, description: 요일 한 글자, values: auto}
      - {name: start_time, type: TIME, description: 시작 시각, values: auto}
      - {name: end_time, type: TIME, description: 종료 시각, values: auto}
      - {name: classroom, type: VARCHAR, description: 강의실, values: auto}
      - {name: prereq_subject_codes, type: TEXT, description: "선수과목 코드 목록(쉼표 구분, 없으면 '없음')", values: auto}
      - {name: prereq_subject_names, type: TEXT, description: "선수과목명 목록(쉼표 구분, 없으면 '없음')", values: auto}
  - name: student
    description: 학생. 로그인한 본인 행만 조회 가능
    columns:
      - {name: student_id, type: VARCHAR, description: 학번, values: none}
      - {name: dept_code, type: VARCHAR, description: 소속 학과 코드(department.dept_code), values: none}
      - {name: grade, type: INTEGER, description: 현재 학년, values: none}
      - {name: admission_year, type: INTEGER, description: 입학 연도, values: none}
  - name: enrollment
    description: 학생의 수강 이력. 로그인한 본인 행만 조회 가능
    columns:
      - {name: student_id, type: VARCHAR, description: 학번, values: none}
      - {name: subject_code, type: VARCHAR, description: 이수한 교과목 코드, values: none}
      - {name: letter_grade, type: VARCHAR, description: 성적, values: auto}
      - {name: enroll_year, type: INTEGER, description: 수강 연도, values: auto}
      - {name: semester, type: VARCHAR, description: 학기, values: auto}
  - name: subject
    description: 교과목 마스터(과목명·이수구분·학점)
    columns:
      - {name: subject_code, type: VARCHAR, description: 교과목 코드, values: none}
      - {name: subject_name, type: VARCHAR, description: 과목명, values: none}
      - {name: category, type: VARCHAR, description: 이수구분, values: auto}
      - {name: credit_hours, type: VARCHAR, description: 학점/이론/실습, values: none}
  - name: department
    description: 학과
    columns:
      - {name: dept_code, type: VARCHAR, description: 학과 코드, values: none}
      - {name: dept_name, type: VARCHAR, description: 학과 전체 이름(v_course_info.dept_name과 같은 값), values: none}
foreign_keys:
  - enrollment.student_id → student.student_id
  - enrollment.subject_code → subject.subject_code
  - student.dept_code → department.dept_code
  - department.dept_name → v_course_info.dept_name
```

- [ ] **Step 2: 실패하는 테스트** — `backend/t2s/tests/test_schema_doc.py`:

```python
from backend.t2s.schema_doc import build_mschema, load_column_docs

DOCS = {
    "tables": [
        {"name": "t", "description": "설명", "columns": [
            {"name": "a", "type": "VARCHAR", "description": "작은 열", "values": "auto"},
            {"name": "b", "type": "VARCHAR", "description": "큰 열", "values": "auto"},
            {"name": "c", "type": "INTEGER", "description": "비공개", "values": "none"},
        ]},
    ],
    "foreign_keys": ["t.a → u.a"],
}


def fake_fetch(sql, params=None):
    if "COUNT(DISTINCT a)" in sql:
        return [{"n": 2}]
    if "COUNT(DISTINCT b)" in sql:
        return [{"n": 30}]
    if "DISTINCT a" in sql:
        return [{"v": "x"}, {"v": "y"}]
    if "b AS v" in sql:
        return [{"v": "p"}, {"v": "q"}, {"v": "r"}]
    raise AssertionError(sql)


def test_build_mschema_lists_small_columns_fully_and_samples_large_ones():
    text = build_mschema(DOCS, fake_fetch)

    assert text.splitlines()[0] == "# Table: t (설명)"
    assert "(a: VARCHAR, 작은 열, Values: ['x', 'y'])," in text
    assert "(b: VARCHAR, 큰 열, Examples: ['p', 'q', 'r'])," in text
    assert "(c: INTEGER, 비공개)" in text
    assert text.rstrip().endswith("【Foreign keys】\nt.a → u.a")


def test_shipped_yaml_covers_every_v_course_info_column():
    from backend.t2s.postprocess import STANDARD_COLUMNS

    docs = load_column_docs()
    v = next(t for t in docs["tables"] if t["name"] == "v_course_info")

    assert tuple(c["name"] for c in v["columns"]) == STANDARD_COLUMNS
```

- [ ] **Step 3: 실패 확인** — Run: `python -m pytest backend/t2s/tests/test_schema_doc.py -q` / Expected: ImportError.

- [ ] **Step 4: 구현** — `backend/t2s/schema_doc.py`:

```python
"""M-Schema text for the prompt: human-written Korean column docs + values read from the DB."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

DOCS_PATH = Path(__file__).with_name("schema_docs.yaml")
FULL_VALUES_MAX = 20
EXAMPLE_COUNT = 3


def load_column_docs(path: Path = DOCS_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _values_text(table: str, column: str, fetch) -> str:
    count = fetch(f"SELECT COUNT(DISTINCT {column}) AS n FROM {table}")[0]["n"]
    if count <= FULL_VALUES_MAX:
        rows = fetch(f"SELECT DISTINCT {column} AS v FROM {table} WHERE {column} IS NOT NULL ORDER BY 1")
        return f", Values: {[_plain(r['v']) for r in rows]}"
    rows = fetch(
        f"SELECT {column} AS v FROM {table} WHERE {column} IS NOT NULL "
        f"GROUP BY {column} ORDER BY COUNT(*) DESC LIMIT {EXAMPLE_COUNT}"
    )
    return f", Examples: {[_plain(r['v']) for r in rows]}"


def _plain(value):
    return value if isinstance(value, (int, float, str)) else str(value)


def build_mschema(docs: dict, fetch) -> str:
    lines: list[str] = []
    for table in docs["tables"]:
        lines.append(f"# Table: {table['name']} ({table['description']})")
        lines.append("[")
        columns = table["columns"]
        for i, column in enumerate(columns):
            values = _values_text(table["name"], column["name"], fetch) if column.get("values") == "auto" else ""
            comma = "," if i < len(columns) - 1 else ""
            lines.append(f"({column['name']}: {column['type']}, {column['description']}{values}){comma}")
        lines.append("]")
    if docs.get("foreign_keys"):
        lines.append("【Foreign keys】")
        lines.extend(docs["foreign_keys"])
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_mschema() -> str:
    from ..db import run_query

    return build_mschema(load_column_docs(), run_query)
```

`fake_fetch`가 `"COUNT(DISTINCT a)"`와 `"b AS v"`로 분기하므로 SQL 문자열은 위 형태를 유지한다. `backend/requirements.txt`에 `pyyaml` 한 줄 추가.

- [ ] **Step 5: 통과 확인과 실DB 스모크** — Run: `python -m pytest backend/t2s -q` 후 `python -c "from dotenv import load_dotenv; load_dotenv('backend/.env'); from backend.t2s.schema_doc import get_mschema; t=get_mschema(); print(len(t)); print(t[:1500])"` / Expected: 테스트 통과, 출력 길이 약 3,000~6,000자, `category` 줄에 9개 값 전체, `dept_name`에 예시 3개.
- [ ] **Step 6: 커밋** — `feat: build an M-Schema prompt section from Korean column docs and DB values`

---

### Task 4: 값 후보 (`values.py`)

**Files:** Create `backend/t2s/values.py`; Test `backend/t2s/tests/test_values.py`

**Interfaces:**
- `ValueCandidate(column: str, value: str, score: float, source: str)` frozen dataclass
- `VALUE_COLUMNS = ("dept_name", "category", "subject_name", "professor", "class_mode", "eval_type", "grading_method")`
- `LABEL_TO_COLUMN` — `keyword_extract.ENTITY_REFERENCE_MAP`와 같은 매핑을 상수로 복제(무거운 import 회피): CATEGORY→category, COURSE_NAME→subject_name, DEPARTMENT→dept_name, CLASS_MODE→class_mode, EVAL_TYPE→eval_type, GRADE_METHOD→grading_method, PROFESSOR→professor
- `value_key(text) -> str` — 한글·영숫자만 남기고 소문자
- `from_ner(entities: list[dict], references: dict[str, list[str]]) -> list[ValueCandidate]` — 교정 결과(`corrected_text`)가 해당 컬럼의 실제 DB 값과 정확히 같을 때만, score = `similarity`(없으면 100), source "ner"
- `from_ngrams(question: str, references) -> list[ValueCandidate]` — DB 값 전체가 질문에 포함(value_key 기준)되면 100, 값의 공백 단위 토큰 중 3글자 이상 토큰이 질문에 포함되면 90, source "ngram"
- `from_hints(hints: list[dict]) -> list[ValueCandidate]` — score 100, source "gold"
- `merge(candidates, per_column=3) -> list[ValueCandidate]` — 같은 (column, value)는 최고 점수만, 컬럼별 점수 내림차순→값 길이 내림차순 상위 `per_column`, 결과는 VALUE_COLUMNS 순서
- `find_value_candidates(question, entities, references, sources) -> list[ValueCandidate]`
- `load_value_references(fetch) -> dict[str, list[str]]` — VALUE_COLUMNS별 `SELECT DISTINCT col FROM v_course_info WHERE col IS NOT NULL`

- [ ] **Step 1: 실패하는 테스트** — `backend/t2s/tests/test_values.py`:

```python
from backend.t2s.values import (
    ValueCandidate, find_value_candidates, from_hints, from_ner, from_ngrams, merge, value_key,
)

REFS = {
    "dept_name": ["공과대학 컴퓨터융합학부", "공과대학 컴퓨터인공지능학부", "경상대학 경제학과"],
    "category": ["전공(핵심)", "전공(기초)", "교양(소양필수)"],
    "subject_name": ["자료구조", "자료구조및실습", "운영체제"],
    "professor": ["김교수"],
}


def test_value_key_keeps_hangul_and_alnum():
    assert value_key("전공(핵심) A1 ") == "전공핵심a1"


def test_ngrams_full_and_token_matches():
    found = {(c.column, c.value, c.score) for c in from_ngrams("컴퓨터융합학부 전공핵심 자료구조 과목", REFS)}

    assert ("dept_name", "공과대학 컴퓨터융합학부", 90) in found
    assert ("category", "전공(핵심)", 100) in found
    assert ("subject_name", "자료구조", 100) in found
    assert not any(v == "자료구조및실습" for _, v, _ in found)
    assert not any(v == "공과대학 컴퓨터인공지능학부" for _, v, _ in found)


def test_ner_candidates_only_for_exact_db_values():
    entities = [
        {"label": "DEPARTMENT", "corrected_text": "공과대학 컴퓨터융합학부", "similarity": 88.5},
        {"label": "COURSE_NAME", "corrected_text": "없는과목", "similarity": 70.0},
        {"label": "DAY", "corrected_text": "목"},
    ]

    assert from_ner(entities, REFS) == [ValueCandidate("dept_name", "공과대학 컴퓨터융합학부", 88.5, "ner")]


def test_merge_dedupes_and_caps_per_column():
    merged = merge([
        ValueCandidate("dept_name", "A", 90, "ngram"),
        ValueCandidate("dept_name", "A", 95, "ner"),
        ValueCandidate("dept_name", "BB", 90, "ngram"),
        ValueCandidate("dept_name", "C", 80, "ngram"),
        ValueCandidate("dept_name", "D", 70, "ngram"),
        ValueCandidate("category", "X", 100, "ngram"),
    ], per_column=3)

    assert [(c.column, c.value) for c in merged] == [
        ("dept_name", "A"), ("dept_name", "BB"), ("dept_name", "C"), ("category", "X"),
    ]


def test_hints_replace_search():
    hints = [{"column": "dept_name", "value": "경상대학 경제학과"}]

    assert from_hints(hints) == [ValueCandidate("dept_name", "경상대학 경제학과", 100, "gold")]


def test_find_value_candidates_respects_sources():
    entities = [{"label": "DEPARTMENT", "corrected_text": "공과대학 컴퓨터융합학부", "similarity": 99}]

    ner_only = find_value_candidates("컴융 운영체제", entities, REFS, ("ner",))
    both = find_value_candidates("컴융 운영체제", entities, REFS, ("ner", "ngram"))

    assert [c.value for c in ner_only] == ["공과대학 컴퓨터융합학부"]
    assert {c.value for c in both} == {"공과대학 컴퓨터융합학부", "운영체제"}
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest backend/t2s/tests/test_values.py -q` / Expected: ImportError.

- [ ] **Step 3: 구현** — `backend/t2s/values.py`:

```python
"""Value candidates for the prompt: NER corrections plus an NER-independent n-gram search (spec 3.1)."""
from __future__ import annotations

import re
from dataclasses import dataclass

VALUE_COLUMNS = ("dept_name", "category", "subject_name", "professor", "class_mode", "eval_type", "grading_method")
# Same mapping as keyword_extract.ENTITY_REFERENCE_MAP (copied to avoid importing the NER model).
LABEL_TO_COLUMN = {
    "CATEGORY": "category",
    "COURSE_NAME": "subject_name",
    "DEPARTMENT": "dept_name",
    "CLASS_MODE": "class_mode",
    "EVAL_TYPE": "eval_type",
    "GRADE_METHOD": "grading_method",
    "PROFESSOR": "professor",
}
MIN_TOKEN_LENGTH = 3


@dataclass(frozen=True)
class ValueCandidate:
    column: str
    value: str
    score: float
    source: str


def value_key(text) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(text or "")).lower()


def from_ner(entities: list[dict], references: dict[str, list[str]]) -> list[ValueCandidate]:
    found = []
    for entity in entities:
        column = LABEL_TO_COLUMN.get(entity.get("label"))
        value = entity.get("corrected_text")
        if column and value in references.get(column, ()):
            score = entity.get("similarity")
            found.append(ValueCandidate(column, value, float(score if score is not None else 100), "ner"))
    return found


def from_ngrams(question: str, references: dict[str, list[str]]) -> list[ValueCandidate]:
    question_key = value_key(question)
    found = []
    for column, values in references.items():
        for value in values:
            full = value_key(value)
            if full and full in question_key:
                found.append(ValueCandidate(column, value, 100.0, "ngram"))
                continue
            tokens = [value_key(t) for t in str(value).split()]
            if any(len(t) >= MIN_TOKEN_LENGTH and t in question_key for t in tokens):
                found.append(ValueCandidate(column, value, 90.0, "ngram"))
    return found


def from_hints(hints: list[dict]) -> list[ValueCandidate]:
    return [ValueCandidate(h["column"], h["value"], 100.0, "gold") for h in hints]


def merge(candidates: list[ValueCandidate], per_column: int = 3) -> list[ValueCandidate]:
    best: dict[tuple[str, str], ValueCandidate] = {}
    for candidate in candidates:
        key = (candidate.column, candidate.value)
        if key not in best or candidate.score > best[key].score:
            best[key] = candidate
    ordered: list[ValueCandidate] = []
    columns = list(VALUE_COLUMNS) + sorted({c.column for c in best.values()} - set(VALUE_COLUMNS))
    for column in columns:
        group = [c for c in best.values() if c.column == column]
        group.sort(key=lambda c: (-c.score, -len(c.value)))
        ordered.extend(group[:per_column])
    return ordered


def find_value_candidates(question, entities, references, sources) -> list[ValueCandidate]:
    found: list[ValueCandidate] = []
    if "ner" in sources:
        found += from_ner(entities or [], references)
    if "ngram" in sources:
        found += from_ngrams(question, references)
    return merge(found)


def load_value_references(fetch) -> dict[str, list[str]]:
    return {
        column: [r["v"] for r in fetch(f"SELECT DISTINCT {column} AS v FROM v_course_info WHERE {column} IS NOT NULL")]
        for column in VALUE_COLUMNS
    }
```

- [ ] **Step 4: 통과 확인** — Run: `python -m pytest backend/t2s -q` / Expected: 통과.
- [ ] **Step 5: 커밋** — `feat: find value candidates from NER corrections and DB n-grams`

---

### Task 5: 검증된 예시 저장소 (`examples.py`)

**Files:** Create `backend/t2s/examples.py`, `backend/t2s/data/examples.json`(초기값 `[]`); Test `backend/t2s/tests/test_examples.py`

**Interfaces:**
- `Example(id: str, question: str, sql: str)` frozen dataclass
- `EXAMPLES_PATH`, `load_examples(path=EXAMPLES_PATH) -> list[Example]`, `save_examples(examples, path)`
- `sql_skeleton(sql) -> str` — 문자열 리터럴→`'?'`, 숫자→`0`, 공백 정리, 소문자
- `ExampleStore(examples, embed)` + `.search(question, k) -> list[tuple[Example, float]]` — 코사인 유사도 내림차순, 골격이 이미 뽑힌 것과 같으면 건너뜀
- `embed_question(text) -> numpy.ndarray` — `vector_cache.embed_text` 바이트를 float32 벡터로(지연 import)
- `contamination(examples, golden_cases, embed, threshold=0.9) -> list[str]` — 문제 설명 목록(유사 질의, 동일 SQL)
- `default_store() -> ExampleStore` — lru_cache
- CLI: `python -m backend.t2s.examples check`(오염 검사, 문제 있으면 종료 코드 1), `python -m backend.t2s.examples approve --log-line N --id ID`(검토 로그 N번째 줄의 질문·SQL을 예시로 추가, 오염 검사 통과 시)

- [ ] **Step 1: 실패하는 테스트** — `backend/t2s/tests/test_examples.py`:

```python
import json

import numpy as np

from backend.t2s.examples import Example, ExampleStore, contamination, load_examples, save_examples, sql_skeleton

VECTORS = {
    "컴융 목요일 과목": [1.0, 0.0, 0.0],
    "컴융 금요일 과목": [0.99, 0.14, 0.0],
    "선수과목 알려줘": [0.0, 1.0, 0.0],
    "질문": [1.0, 0.05, 0.0],
}


def embed(text):
    v = np.array(VECTORS[text], dtype=np.float32)
    return v / np.linalg.norm(v)


EXAMPLES = [
    Example("e1", "컴융 목요일 과목", "SELECT * FROM v_course_info WHERE day_of_week = '목'"),
    Example("e2", "컴융 금요일 과목", "SELECT * FROM v_course_info WHERE day_of_week = '금'"),
    Example("e3", "선수과목 알려줘", "SELECT prereq_subject_names FROM v_course_info"),
]


def test_sql_skeleton_masks_literals():
    assert sql_skeleton("SELECT *  FROM v WHERE a = '목' AND b = 3") == "select * from v where a = '?' and b = 0"


def test_search_orders_by_similarity_and_skips_duplicate_skeletons():
    store = ExampleStore(EXAMPLES, embed)

    hits = store.search("질문", k=2)

    assert [e.id for e, _ in hits] == ["e1", "e3"]
    assert hits[0][1] > hits[1][1]


def test_load_and_save_round_trip(tmp_path):
    path = tmp_path / "ex.json"
    save_examples(EXAMPLES, path)

    assert load_examples(path) == EXAMPLES
    assert json.loads(path.read_text(encoding="utf-8"))[0]["question"] == "컴융 목요일 과목"


def test_contamination_flags_similar_questions_and_identical_sql():
    golden = [
        {"id": "g1", "query": "컴융 금요일 과목", "reference_sql": "SELECT 1"},
        {"id": "g2", "query": "선수과목 알려줘", "reference_sql": "SELECT prereq_subject_names FROM v_course_info"},
    ]

    problems = contamination(EXAMPLES[2:], golden, embed)

    assert any("e3" in p and "g2" in p for p in problems)
    assert contamination([EXAMPLES[0]], golden[:1], embed, threshold=0.995) == []
```

- [ ] **Step 2: 실패 확인** — ImportError.

- [ ] **Step 3: 구현** — `backend/t2s/examples.py`:

```python
"""Verified question→SQL examples for few-shot prompting (spec 3.3), kept apart from the golden set."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

EXAMPLES_PATH = Path(__file__).with_name("data") / "examples.json"
REVIEW_LOG_PATH = Path(__file__).with_name("logs") / "review_queue.jsonl"
CONTAMINATION_THRESHOLD = 0.9


@dataclass(frozen=True)
class Example:
    id: str
    question: str
    sql: str


def load_examples(path: Path = EXAMPLES_PATH) -> list[Example]:
    with open(path, encoding="utf-8") as fh:
        return [Example(**item) for item in json.load(fh)]


def save_examples(examples: list[Example], path: Path = EXAMPLES_PATH) -> None:
    Path(path).write_text(
        json.dumps([asdict(e) for e in examples], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sql_skeleton(sql: str) -> str:
    text = re.sub(r"'(?:[^']|'')*'", "'?'", sql)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "0", text)
    return re.sub(r"\s+", " ", text).strip().lower()


class ExampleStore:
    def __init__(self, examples: list[Example], embed):
        self.examples = list(examples)
        self._embed = embed
        self._matrix = np.vstack([embed(e.question) for e in self.examples]) if self.examples else None

    def search(self, question: str, k: int) -> list[tuple[Example, float]]:
        if self._matrix is None or k <= 0:
            return []
        scores = self._matrix @ self._embed(question)
        picked, skeletons = [], set()
        for index in np.argsort(-scores):
            example = self.examples[int(index)]
            skeleton = sql_skeleton(example.sql)
            if skeleton in skeletons:
                continue
            skeletons.add(skeleton)
            picked.append((example, float(scores[int(index)])))
            if len(picked) == k:
                break
        return picked


def embed_question(text: str) -> np.ndarray:
    from ..vector_cache import embed_text

    return np.frombuffer(embed_text(text), dtype=np.float32)


def contamination(examples, golden_cases, embed, threshold: float = CONTAMINATION_THRESHOLD) -> list[str]:
    problems = []
    golden_sql = {(c.get("reference_sql") or "").strip(): c["id"] for c in golden_cases if c.get("reference_sql")}
    golden_vectors = [(c["id"], embed(c["query"])) for c in golden_cases]
    for example in examples:
        if example.sql.strip() in golden_sql:
            problems.append(f"{example.id}: 평가셋 {golden_sql[example.sql.strip()]}와 정답 SQL 동일")
        vector = embed(example.question)
        for case_id, golden_vector in golden_vectors:
            similarity = float(vector @ golden_vector)
            if similarity >= threshold:
                problems.append(f"{example.id}: 평가셋 {case_id}와 질의 유사도 {similarity:.3f}")
    return problems


@lru_cache(maxsize=1)
def default_store() -> ExampleStore:
    return ExampleStore(load_examples(), embed_question)


def main(argv=None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="검증된 예시 저장소")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    approve = sub.add_parser("approve")
    approve.add_argument("--log-line", type=int, required=True)
    approve.add_argument("--id", required=True)
    args = parser.parse_args(argv)

    from ..eval.run_eval import GOLDEN_QUERIES_PATH, load_cases

    golden = load_cases(GOLDEN_QUERIES_PATH)
    examples = load_examples()
    if args.command == "approve":
        lines = REVIEW_LOG_PATH.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[args.log_line - 1])
        candidate = Example(args.id, record["query"], record["sql"])
        problems = contamination([candidate], golden, embed_question)
        if problems or any(e.id == candidate.id for e in examples):
            print("\n".join(problems) or f"id 중복: {candidate.id}")
            return 1
        save_examples(examples + [candidate])
        print(f"추가: {candidate.id}")
        return 0
    problems = contamination(examples, golden, embed_question)
    print(f"예시 {len(examples)}개, 문제 {len(problems)}건")
    print("\n".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`backend/t2s/data/examples.json`은 `[]`로 만든다.

- [ ] **Step 4: 통과 확인** — `python -m pytest backend/t2s -q`
- [ ] **Step 5: 커밋** — `feat: add the verified example store with contamination checks`

---

### Task 6: 예시 저장소 초기 데이터 (약 150개)

**Files:** Modify `backend/t2s/data/examples.json`

**Interfaces:** Consumes `python -m backend.t2s.examples check`. Produces 예시 약 150개.

작성 규칙:
1. 질의 유형별 대표 SQL 골격을 고르게: 강의 검색(학과·이수구분·요일·시간·학년·학점·교수·강의방식·여석 조합) 60, 선수과목 15, 집계(개수·최대/최소·여석·그룹별) 25, 개인화 조회(본인 학과·학년, 수강 이력·성적, 내 학과 개설 과목) 25, 거부(UNKNOWN 정답) 15, 이수 과목 제외 질의 10(SQL에는 제외 조건 없이 나머지 조건만 — 파이프라인이 붙이므로).
2. SQL은 v2 프롬프트 규칙을 그대로 따르는 모범답안: 강의 목록은 `SELECT * FROM v_course_info WHERE ...`, 학과·과목·교수는 `LIKE '%값%'`(동명 학과가 있으면 대학명까지), 이수구분은 괄호 표기 `=`, 학년은 `target_year`, 학점 `credit_hours LIKE '3/%'`, 개수 `COUNT(DISTINCT subject_code || '-' || section) AS course_count`, 학생 질의는 별칭과 `s.student_id = %(student_id)s` / `e.student_id = %(student_id)s`를 WHERE에 AND로. 거부 예시의 `sql`은 `UNKNOWN`.
3. 모든 SQL은 실제 DB에서 실행해 1행 이상(거부 제외). 학생 SQL은 `%(student_id)s`를 `'202102671'`로 바꿔 실행 확인하고, `backend.validate.validate_generated_sql(sql + LIMIT, requested_student_id='202102671')` 통과.
4. 질문은 학생이 쓸 법한 한국어(약어·구어체 40% 이상), id는 `ex_001`부터.
5. **평가셋과 겹치지 않기**: `python -m backend.t2s.examples check`가 문제 0건(평가셋 질의와 KURE 유사도 0.9 미만, 정답 SQL과 다름). 평가셋 질의를 보고 바꿔 쓰지 말고, 평가셋에 없는 학과·과목·조건 조합을 쓴다.

- [ ] **Step 1:** 작성(보조 스크립트는 scratchpad에만), 30개마다 `check` 실행.
- [ ] **Step 2:** Run: `python -m backend.t2s.examples check && python -m pytest backend/t2s -q` / Expected: 문제 0건, 통과.
- [ ] **Step 3: 커밋** — `test: seed the verified example store`

---

### Task 7: 프롬프트 (`prompt.py`)

**Files:** Create `backend/t2s/prompt.py`; Test `backend/t2s/tests/test_prompt.py`

**Interfaces:**
- `SYSTEM_INSTRUCTION: str`, `DOMAIN_RULES: tuple[str, ...]`, `STUDENT_RULE`, `ANON_RULE`, `EXCLUDE_RULE`
- `build_messages(question: str, *, schema: str, hints: list[ValueCandidate], examples: list[Example], logged_in: bool, exclude_completed: bool) -> list[dict]` — `[system, (user, assistant)×examples, user]`

- [ ] **Step 1: 실패하는 테스트** — `backend/t2s/tests/test_prompt.py`:

```python
from backend.t2s.examples import Example
from backend.t2s.prompt import ANON_RULE, EXCLUDE_RULE, STUDENT_RULE, build_messages
from backend.t2s.values import ValueCandidate


def test_message_layout():
    messages = build_messages(
        "컴융 목요일 과목",
        schema="# Table: v_course_info",
        hints=[ValueCandidate("dept_name", "공과대학 컴퓨터융합학부", 90, "ngram")],
        examples=[Example("e1", "질문1", "SELECT 1"), Example("e2", "질문2", "UNKNOWN")],
        logged_in=False,
        exclude_completed=False,
    )

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert "# Table: v_course_info" in messages[0]["content"]
    assert ANON_RULE in messages[0]["content"] and STUDENT_RULE not in messages[0]["content"]
    assert messages[1]["content"] == "질문: 질문1" and messages[2]["content"] == "SELECT 1"
    assert "dept_name = '공과대학 컴퓨터융합학부'" in messages[-1]["content"]
    assert messages[-1]["content"].endswith("질문: 컴융 목요일 과목")


def test_student_and_exclusion_rules():
    content = build_messages("q", schema="s", hints=[], examples=[], logged_in=True, exclude_completed=True)[0]["content"]

    assert STUDENT_RULE in content and EXCLUDE_RULE in content


def test_no_hint_block_when_no_hints():
    last = build_messages("q", schema="s", hints=[], examples=[], logged_in=False, exclude_completed=False)[-1]

    assert last["content"] == "질문: q"
```

- [ ] **Step 2: 실패 확인** — ImportError.

- [ ] **Step 3: 구현** — `backend/t2s/prompt.py`:

```python
"""Chat messages for SQL generation (spec 4)."""
from __future__ import annotations

SYSTEM_INSTRUCTION = (
    "너는 대학 수강신청 데이터베이스(PostgreSQL)의 SQL 생성기다. 한국어 질문을 SELECT 문 하나로 바꾼다. "
    "SQL만 출력하고 설명하지 않는다. 스키마로 답할 수 없거나 질문이 모호하거나 쓰기·삭제·다른 학생 정보 요청이면 UNKNOWN 한 단어만 출력한다."
)
DOMAIN_RULES = (
    "강의 목록을 묻는 질문은 SELECT * FROM v_course_info WHERE ... 형태로 쓴다.",
    "학과명·과목명·교수명은 LIKE '%값%'으로 찾고, 값 후보가 주어지면 그 정확한 값을 쓴다.",
    "이수구분(category)은 '전공(핵심)'처럼 괄호 표기로 비교한다. 전공핵심·전핵→'전공(핵심)', 교필→'교양(소양필수)'.",
    "'N학년 대상', 'N학년 과목'은 target_year = N이다. course_year는 쓰지 않는다.",
    "학점 조건은 credit_hours LIKE 'N/%'로 쓴다(값 형식 '학점/이론/실습').",
    "'1시~7시'는 13~19시다. 'N시 수업'은 start_time = 'HH:00:00', 오전은 start_time < '12:00:00', 오후는 start_time >= '12:00:00'.",
    "과목·분반 수는 COUNT(DISTINCT subject_code || '-' || section) AS course_count로 센다.",
    "여석은 capacity - enrolled, '여석 있음'은 enrolled < capacity AND capacity > 0, '마감'은 enrolled >= capacity AND capacity > 0.",
    "선수과목은 prereq_subject_names(없으면 '없음')를 쓴다.",
)
STUDENT_RULE = (
    "로그인한 학생 본인 정보는 student AS s, enrollment AS e처럼 별칭을 쓰고 WHERE에 "
    "s.student_id = %(student_id)s 또는 e.student_id = %(student_id)s를 AND로 둔다. 다른 학생 정보는 UNKNOWN."
)
ANON_RULE = "로그인하지 않은 사용자다. student·enrollment가 필요한 개인 질문은 UNKNOWN."
EXCLUDE_RULE = "이미 들은 과목 제외는 시스템이 처리하므로 SQL에 넣지 말고 나머지 조건만 쓴다."


def _system_content(schema: str, logged_in: bool, exclude_completed: bool) -> str:
    rules = list(DOMAIN_RULES) + [STUDENT_RULE if logged_in else ANON_RULE]
    if exclude_completed:
        rules.append(EXCLUDE_RULE)
    return f"{SYSTEM_INSTRUCTION}\n\n[스키마]\n{schema}\n\n[규칙]\n" + "\n".join(f"- {r}" for r in rules)


def _user_content(question: str, hints) -> str:
    if not hints:
        return f"질문: {question}"
    lines = "\n".join(f"- {h.column} = '{h.value}'" for h in hints)
    return f"[값 후보 — 참고용, 틀릴 수 있음]\n{lines}\n\n질문: {question}"


def build_messages(question, *, schema, hints, examples, logged_in, exclude_completed) -> list[dict]:
    messages = [{"role": "system", "content": _system_content(schema, logged_in, exclude_completed)}]
    for example in examples:
        messages.append({"role": "user", "content": f"질문: {example.question}"})
        messages.append({"role": "assistant", "content": example.sql})
    messages.append({"role": "user", "content": _user_content(question, hints)})
    return messages
```

- [ ] **Step 4: 통과 확인**, **Step 5: 커밋** — `feat: assemble v2 chat messages with schema, rules, hints and examples`

---

### Task 8: 후보 생성 (`generate.py`)과 거부 판정 이동

**Files:** Create `backend/t2s/generate.py`; Modify `backend/validate.py`(아래 함수 추가), `backend/eval/run_eval.py`(이동한 함수 사용); Test `backend/t2s/tests/test_generate.py`, 기존 `backend/eval/test_run_eval.py` 통과 유지

**Interfaces:**
- `backend.validate.is_safety_rejection(message) -> bool` — `run_eval.SAFETY_REJECTION_PATTERNS`와 `AMBIGUOUS_QUERY_ERROR`를 validate.py로 옮긴다(정규식·문구 그대로). run_eval은 `from ..validate import is_safety_rejection`를 쓰고 `is_rejection_error = is_safety_rejection`으로 이름을 유지한다(기존 테스트 호환).
- `generate.extract_sql(text: str | None) -> str | None` — 코드펜스 제거, `UNKNOWN`으로 시작하면 `"UNKNOWN"`, 첫 `SELECT`/`WITH`부터 첫 `;` 전까지(없으면 끝까지), 없으면 None
- `generate.ollama_chat(messages, *, model, temperature, seed=None, timeout=120.0) -> str` — POST `{OLLAMA_BASE_URL}/api/chat` `{"model", "messages", "stream": False, "options": {"temperature", "num_predict": 512, "seed"(있을 때)}}` → `body["message"]["content"]`; 연결·HTTP·JSON·형식 오류는 `RuntimeError`
- `generate.generate_candidates(message_sets: list[list[dict]], *, model, temperature, chat=ollama_chat) -> list[str | None]` — i=0은 온도 0, 나머지는 `temperature`와 seed=i, ThreadPoolExecutor(최대 len), 예외는 None, 순서 보존

- [ ] **Step 1: 실패하는 테스트** — `backend/t2s/tests/test_generate.py`:

```python
import pytest

from backend.t2s.generate import extract_sql, generate_candidates


@pytest.mark.parametrize("text, expected", [
    ("SELECT 1 FROM v_course_info;", "SELECT 1 FROM v_course_info"),
    ("```sql\nSELECT a\nFROM t\n```", "SELECT a\nFROM t"),
    ("답: select a from t; 추가 설명", "select a from t"),
    ("UNKNOWN", "UNKNOWN"),
    ("unknown.", "UNKNOWN"),
    ("WITH x AS (SELECT 1) SELECT * FROM x", "WITH x AS (SELECT 1) SELECT * FROM x"),
    ("모르겠어요", None),
    (None, None),
])
def test_extract_sql(text, expected):
    assert extract_sql(text) == expected


def test_generate_candidates_uses_greedy_first_and_keeps_order():
    calls = []

    def chat(messages, *, model, temperature, seed=None):
        calls.append((messages[0]["content"], temperature, seed))
        if messages[0]["content"] == "boom":
            raise RuntimeError("down")
        return f"SELECT {messages[0]['content']}"

    sets = [[{"role": "user", "content": c}] for c in ("a", "boom", "c")]

    out = generate_candidates(sets, model="m", temperature=0.7, chat=chat)

    assert out == ["SELECT a", None, "SELECT c"]
    assert sorted(calls) == sorted([("a", 0.0, None), ("boom", 0.7, 1), ("c", 0.7, 2)])
```

`backend/test_validate_student.py` 또는 새 `backend/t2s/tests/test_rejection.py`에 추가:

```python
from backend.validate import is_safety_rejection


def test_is_safety_rejection_matches_ambiguity_and_validator_reasons():
    assert is_safety_rejection("질문이 모호합니다.")
    assert is_safety_rejection("SELECT 문만 허용됩니다.")
    assert not is_safety_rejection("기본 LIMIT가 필요합니다.")
    assert not is_safety_rejection(None)
```

- [ ] **Step 2: 실패 확인** — ImportError.

- [ ] **Step 3: 구현** — `backend/validate.py`에 run_eval의 `AMBIGUOUS_QUERY_ERROR`, `SAFETY_REJECTION_PATTERNS`를 그대로 옮기고:

```python
def is_safety_rejection(message) -> bool:
    if not isinstance(message, str):
        return False
    return message == AMBIGUOUS_QUERY_ERROR or any(p.search(message) for p in SAFETY_REJECTION_PATTERNS)
```

run_eval에서 정의를 지우고 `from ..validate import AMBIGUOUS_QUERY_ERROR, SAFETY_REJECTION_PATTERNS, is_safety_rejection`, `is_rejection_error = is_safety_rejection`. (run_eval 테스트가 이 이름들을 import하면 그대로 동작해야 한다.)

`backend/t2s/generate.py`:

```python
"""Candidate SQL generation through Ollama's chat API (spec 3 ④)."""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib import error, request

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_START = re.compile(r"\b(select|with)\b", re.IGNORECASE)


def extract_sql(text: str | None) -> str | None:
    if not text:
        return None
    fenced = _FENCE.search(text)
    body = fenced.group(1) if fenced else text
    if body.strip().upper().startswith("UNKNOWN"):
        return "UNKNOWN"
    start = _START.search(body)
    if not start:
        return None
    sql = body[start.start():].split(";", 1)[0].strip()
    return sql or None


def ollama_chat(messages, *, model, temperature, seed=None, timeout: float = 120.0) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("OLLAMA_BASE_URL is not set")
    options = {"temperature": temperature, "num_predict": 512}
    if seed is not None:
        options["seed"] = seed
    payload = {"model": model, "messages": messages, "stream": False, "options": options}
    req = request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
    except error.HTTPError as exc:
        raise RuntimeError(f"Ollama request failed: HTTP {exc.code}") from exc
    except OSError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    try:
        body = json.loads(raw.decode("utf-8"))
        content = body["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("unexpected Ollama chat response") from exc
    if not isinstance(content, str):
        raise RuntimeError("unexpected Ollama chat response")
    return content


def generate_candidates(message_sets, *, model, temperature, chat=ollama_chat) -> list[str | None]:
    def one(index_and_messages):
        index, messages = index_and_messages
        try:
            if index == 0:
                return chat(messages, model=model, temperature=0.0)
            return chat(messages, model=model, temperature=temperature, seed=index)
        except Exception:
            return None

    if not message_sets:
        return []
    with ThreadPoolExecutor(max_workers=len(message_sets)) as pool:
        return list(pool.map(one, enumerate(message_sets)))
```

주의: 테스트의 `chat`은 온도 0 호출에 seed 인자를 받지 않으므로(기본 None) 위처럼 index 0은 seed를 넘기지 않는다.

- [ ] **Step 4: 통과 확인** — `python -m pytest backend/t2s backend/eval backend/test_validate_student.py backend/test_validate_security.py -q`
- [ ] **Step 5: 커밋** — `feat: generate SQL candidates via Ollama chat and share the rejection matcher`

---

### Task 9: 후보 실행 (`execute.py`)

**Files:** Create `backend/t2s/execute.py`; Test `backend/t2s/tests/test_execute.py`

**Interfaces:**
- `CandidateOutcome(index: int, raw: str | None, sql: str | None, executed_sql: str | None, rows: list[dict] | None, error: str | None, rejected: bool)` dataclass
- `bind_student(sql, student_id) -> tuple[str, dict | None]` — `%(student_id)s`가 있으면 다른 `%`를 `%%`로 바꾸고 `{"student_id": student_id}`, 없으면 `(sql, None)`
- `run_sql(sql, params, timeout_ms) -> list[dict]` — `DATABASE_URL`로 접속, `options=f"-c statement_timeout={timeout_ms}"`, 결과 dict 목록, 커넥션 항상 close
- `run_candidate(index, raw, *, student_id, exclude_completed, settings, run=run_sql, validate=validate_generated_sql, expand=None, exclude=None) -> CandidateOutcome`

처리 순서: `extract_sql(raw)` → None이면 error "SQL 없음" / `"UNKNOWN"`이면 rejected → `row = is_course_row_query(sql)` → `sql = ensure_limit(normalize_projection(sql), settings.row_cap)` → `validate(sql, requested_student_id=student_id)` 실패 시 `is_safety_rejection(reason)`이면 rejected, 아니면 error=reason → 실행 SQL: row이면 `expand(sql)`(기본 `process.expand_schedule_filtered_course_rows`), `exclude_completed`이고 student_id가 있으면 `exclude(sql, student_id)`(기본 `process.exclude_completed_courses_sql`) → `bind_student` → `run(...)`, 예외는 error=str(exc).

- [ ] **Step 1: 실패하는 테스트** — `backend/t2s/tests/test_execute.py`:

```python
from backend.t2s.config import Settings
from backend.t2s.execute import bind_student, run_candidate

SETTINGS = Settings("m", 5, 0.7, 4, True, ("ner", "ngram"), 50, 3000, False)


def ok_validate(sql, requested_student_id=None):
    return {"ok": True, "reason": None}


def test_bind_student_escapes_other_percents():
    sql, params = bind_student("SELECT 1 FROM e WHERE e.student_id = %(student_id)s AND x LIKE '%a%'", "202102671")

    assert sql == "SELECT 1 FROM e WHERE e.student_id = %(student_id)s AND x LIKE '%%a%%'"
    assert params == {"student_id": "202102671"}
    assert bind_student("SELECT '%a%'", None) == ("SELECT '%a%'", None)


def test_unknown_is_rejected_without_running():
    outcome = run_candidate(0, "UNKNOWN", student_id=None, exclude_completed=False, settings=SETTINGS,
                            run=lambda *a: (_ for _ in ()).throw(AssertionError()), validate=ok_validate)

    assert outcome.rejected and outcome.rows is None


def test_course_row_query_is_normalized_limited_expanded_and_run():
    seen = {}

    def run(sql, params, timeout_ms):
        seen["sql"], seen["params"], seen["timeout"] = sql, params, timeout_ms
        return [{"subject_code": "A"}]

    outcome = run_candidate(
        1, "SELECT subject_name FROM v_course_info WHERE day_of_week = '목'",
        student_id=None, exclude_completed=False, settings=SETTINGS, run=run, validate=ok_validate,
        expand=lambda sql: sql + " /*x*/", exclude=lambda sql, sid: sql,
    )

    assert outcome.rows == [{"subject_code": "A"}] and outcome.error is None
    assert "v_course_info.course_year" in outcome.sql and outcome.sql.endswith("LIMIT 50")
    assert seen["sql"].endswith("/*x*/") and seen["params"] is None and seen["timeout"] == 3000


def test_validation_safety_failure_is_a_rejection_other_failure_is_an_error():
    def deny(reason):
        return lambda sql, requested_student_id=None: {"ok": False, "reason": reason}

    kwargs = dict(student_id=None, exclude_completed=False, settings=SETTINGS, run=lambda *a: [])

    assert run_candidate(0, "SELECT 1 FROM v_course_info", validate=deny("SELECT 문만 허용됩니다."), **kwargs).rejected
    other = run_candidate(0, "SELECT 1 FROM v_course_info", validate=deny("기본 LIMIT가 필요합니다."), **kwargs)
    assert not other.rejected and other.error == "기본 LIMIT가 필요합니다."


def test_exclusion_and_binding_for_student_queries():
    seen = {}

    def run(sql, params, timeout_ms):
        seen["sql"], seen["params"] = sql, params
        return []

    run_candidate(
        0, "SELECT COUNT(*) FROM v_course_info", student_id="202102671", exclude_completed=True,
        settings=SETTINGS, run=run, validate=ok_validate,
        expand=lambda sql: sql, exclude=lambda sql, sid: f"{sql} /*ex {sid}*/",
    )

    assert seen["sql"].endswith("/*ex 202102671*/") and seen["params"] is None


def test_runtime_error_is_recorded():
    def run(sql, params, timeout_ms):
        raise RuntimeError("canceling statement due to statement timeout")

    outcome = run_candidate(0, "SELECT 1 FROM v_course_info", student_id=None, exclude_completed=False,
                            settings=SETTINGS, run=run, validate=ok_validate, expand=lambda s: s, exclude=lambda s, i: s)

    assert outcome.rows is None and "timeout" in outcome.error
```

- [ ] **Step 2: 실패 확인** — ImportError.

- [ ] **Step 3: 구현** — `backend/t2s/execute.py`:

```python
"""Validate, rewrite and run one candidate SQL (spec 3 ⑤)."""
from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg2

from ..validate import is_safety_rejection, validate_generated_sql
from .generate import extract_sql
from .postprocess import ensure_limit, is_course_row_query, normalize_projection

STUDENT_PLACEHOLDER = "%(student_id)s"


@dataclass
class CandidateOutcome:
    index: int
    raw: str | None
    sql: str | None = None
    executed_sql: str | None = None
    rows: list[dict] | None = None
    error: str | None = None
    rejected: bool = False


def bind_student(sql: str, student_id):
    if STUDENT_PLACEHOLDER not in sql:
        return sql, None
    escaped = sql.replace("%", "%%").replace("%%(student_id)s", STUDENT_PLACEHOLDER)
    return escaped, {"student_id": student_id}


def run_sql(sql: str, params, timeout_ms: int) -> list[dict]:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg2.connect(dsn, connect_timeout=5, options=f"-c statement_timeout={int(timeout_ms)}")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d[0] for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _default_expand(sql):
    from ..process import expand_schedule_filtered_course_rows

    return expand_schedule_filtered_course_rows(sql)


def _default_exclude(sql, student_id):
    from ..process import exclude_completed_courses_sql

    return exclude_completed_courses_sql(sql, student_id)


def run_candidate(index, raw, *, student_id, exclude_completed, settings,
                  run=run_sql, validate=validate_generated_sql, expand=None, exclude=None) -> CandidateOutcome:
    outcome = CandidateOutcome(index=index, raw=raw)
    sql = extract_sql(raw)
    if sql is None:
        outcome.error = "SQL 없음"
        return outcome
    if sql == "UNKNOWN":
        outcome.rejected = True
        return outcome

    course_rows = is_course_row_query(sql)
    sql = ensure_limit(normalize_projection(sql), settings.row_cap)
    outcome.sql = sql
    verdict = validate(sql, requested_student_id=student_id)
    if not verdict["ok"]:
        if is_safety_rejection(verdict["reason"]):
            outcome.rejected = True
        else:
            outcome.error = verdict["reason"]
        return outcome

    executable = (expand or _default_expand)(sql) if course_rows else sql
    if exclude_completed and student_id:
        executable = (exclude or _default_exclude)(executable, student_id)
    outcome.executed_sql = executable
    bound_sql, params = bind_student(executable, student_id)
    try:
        outcome.rows = run(bound_sql, params, settings.statement_timeout_ms)
    except Exception as exc:
        outcome.error = str(exc)
    return outcome
```

- [ ] **Step 4: 통과 확인**, **Step 5: 커밋** — `feat: validate, rewrite and run v2 candidates with student binding`

---

### Task 10: 다수결 (`vote.py`)

**Files:** Create `backend/t2s/vote.py`; Test `backend/t2s/tests/test_vote.py`

**Interfaces:**
- `result_signature(rows) -> frozenset`
- `Decision(kind: Literal["answer", "empty", "rejected", "none"], index: int | None)`
- `decide(outcomes: list[CandidateOutcome], total: int) -> Decision` — 거부 후보 수 × 2 > total이면 rejected. 실행 성공 후보 중 비어 있지 않은 결과가 있으면 그 결과들을 서명으로 묶어 (묶음 크기 내림차순, 묶음 내 최소 index 오름차순)으로 고른 answer(index = 묶음 최소 index). 성공 후보가 모두 빈 결과면 empty(가장 작은 index). 성공 후보가 없으면 none.

- [ ] **Step 1: 실패하는 테스트** — `backend/t2s/tests/test_vote.py`:

```python
from backend.t2s.execute import CandidateOutcome
from backend.t2s.vote import Decision, decide, result_signature


def out(i, rows=None, error=None, rejected=False):
    return CandidateOutcome(index=i, raw="x", rows=rows, error=error, rejected=rejected)


A = [{"subject_code": "A", "n": 1}]
B = [{"subject_code": "B", "n": 1}]


def test_signature_ignores_row_and_key_order():
    assert result_signature([{"a": 1, "b": 2}, {"a": 3, "b": 4}]) == result_signature([{"b": 4, "a": 3}, {"b": 2, "a": 1}])


def test_majority_group_wins_and_picks_lowest_index():
    assert decide([out(0, B), out(1, A), out(2, A), out(3, error="x")], 5) == Decision("answer", 1)


def test_tie_prefers_group_containing_greedy_candidate():
    assert decide([out(0, A), out(1, B)], 2) == Decision("answer", 0)


def test_non_empty_beats_larger_empty_group():
    assert decide([out(0, []), out(1, []), out(2, A)], 3) == Decision("answer", 2)


def test_all_empty_and_no_success():
    assert decide([out(0, []), out(1, error="e")], 2) == Decision("empty", 0)
    assert decide([out(0, error="e"), out(1)], 2) == Decision("none", None)


def test_rejection_majority():
    assert decide([out(0, rejected=True), out(1, rejected=True), out(2, rejected=True), out(3, A)], 5) == Decision("rejected", None)
    assert decide([out(0, rejected=True), out(1, rejected=True), out(2, A)], 5) == Decision("answer", 2)
```

- [ ] **Step 2: 실패 확인**, **Step 3: 구현** — `backend/t2s/vote.py`:

```python
"""Execution-result majority vote over candidates (spec 3 ⑥)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal


def result_signature(rows) -> frozenset:
    return frozenset(tuple(sorted((key, repr(value)) for key, value in row.items())) for row in rows)


@dataclass(frozen=True)
class Decision:
    kind: Literal["answer", "empty", "rejected", "none"]
    index: int | None


def decide(outcomes, total: int) -> Decision:
    if sum(1 for o in outcomes if o.rejected) * 2 > total:
        return Decision("rejected", None)
    succeeded = [o for o in outcomes if o.rows is not None]
    if not succeeded:
        return Decision("none", None)
    non_empty = [o for o in succeeded if o.rows]
    if not non_empty:
        return Decision("empty", min(o.index for o in succeeded))
    groups: dict[frozenset, list[int]] = defaultdict(list)
    for outcome in non_empty:
        groups[result_signature(outcome.rows)].append(outcome.index)
    best = min(groups.values(), key=lambda members: (-len(members), min(members)))
    return Decision("answer", min(best))
```

- [ ] **Step 4: 통과 확인**, **Step 5: 커밋** — `feat: pick v2 answers by execution-result majority`

---

### Task 11: 파이프라인 조립과 연결 (`pipeline.py`, run_eval, main)

**Files:** Create `backend/t2s/pipeline.py`; Modify `backend/eval/run_eval.py`(v2 등록, `T2S_REVIEW_LOG=0` 기본), `backend/main.py`(`T2S_PIPELINE` 전환); Test `backend/t2s/tests/test_pipeline.py`, `backend/eval/test_run_eval.py`(v2 등록 테스트 추가)

**Interfaces:**
- `Deps(preprocess, references, store, schema, chat, run, validate, expand, exclude, settings)` dataclass — 테스트에서 가짜 주입
- `default_deps() -> Deps` — `keyword_extract.preprocess_query(q, fail_open=True)`, `values.load_value_references(db.run_query)`(lru_cache), `examples.default_store()`, `schema_doc.get_mschema()`, `generate.ollama_chat`, `execute.run_sql`, `validate_generated_sql`, `None`(기본 expand/exclude), `config.load_settings()`
- `run_v2(query, *, exclude_completed_courses=False, student_id=None, value_hints=None, deps=None) -> dict`, `run_v2.accepts_value_hints = True`

흐름:
1. `settings = deps.settings`; `preprocessing = deps.preprocess(query)`(entities는 `preprocessing["corrected_entities"]`).
2. 값 후보: `value_hints`가 None이 아니면 `from_hints(value_hints)`, 아니면 `find_value_candidates(query, entities, deps.references, settings.value_sources)`.
3. 예시: `settings.use_examples`이면 `deps.store.search(query, settings.examples_k)`의 Example 목록, 아니면 [].
4. 메시지 세트 N개: i=0은 원래 순서, i≥1은 `random.Random(i).shuffle`한 예시 순서로 `build_messages(...)`(`logged_in = student_id is not None`).
5. `raws = generate_candidates(sets, model=settings.model, temperature=settings.temperature, chat=deps.chat)`.
6. `outcomes = [run_candidate(i, raw, ...)]`; `decision = decide(outcomes, len(raws))`.
7. kind가 `none` 또는 `empty`면 재시도 1회: 첫 후보의 메시지 + `{"role":"assistant","content": raws[0] or ""}` + `{"role":"user","content": f"위 SQL은 실행 결과가 {'오류: '+err if err else '0행'}였다. 질문 의도에 맞게 고친 SQL만 출력해."}` → `deps.chat(..., temperature=0.0)` → `run_candidate(len(outcomes), ...)`; 결과가 비어 있지 않으면 그것을 답으로, 아니면 원래 decision 유지(`empty`면 그 빈 결과를 답으로).
8. 응답: rejected → `{"sql": None, "data": [], "error": "질문이 모호합니다.", "rejected": True, ...}`; none(재시도 실패) → `{"sql": 마지막 후보 sql, "data": [], "error": 첫 오류 메시지 또는 "SQL을 생성하지 못했습니다.", "rejected": False}`; answer/empty → `{"sql": outcome.executed_sql, "data": outcome.rows, "error": None, "rejected": False}`. 공통 키 `cache_hit: False`, `query`, `candidates: [{"index","sql","rows": len 또는 None,"error","rejected"}]`, `timings_ms: {"preprocess_ms","llm_ms","execute_ms","total_ms"}`, `value_candidates: [{"column","value","source"}]`.
9. `settings.review_log`이면 `backend/t2s/logs/review_queue.jsonl`에 `{"ts","query","sql","rows","error"}` 한 줄 추가(디렉터리 자동 생성, 실패해도 응답에 영향 없음).

- [ ] **Step 1: 실패하는 테스트** — `backend/t2s/tests/test_pipeline.py`:

```python
from backend.t2s.config import Settings
from backend.t2s.examples import Example, ExampleStore
from backend.t2s.pipeline import Deps, run_v2

import numpy as np


def settings(**kw):
    base = dict(model="m", candidates=3, temperature=0.7, examples_k=1, use_examples=True,
                value_sources=("ngram",), row_cap=50, statement_timeout_ms=3000, review_log=False)
    base.update(kw)
    return Settings(**base)


def deps(chat, run, **kw):
    store = ExampleStore([Example("e1", "예시", "SELECT 1")], lambda t: np.array([1.0], dtype=np.float32))
    return Deps(
        preprocess=lambda q: {"corrected_entities": []},
        references={"dept_name": ["공과대학 컴퓨터융합학부"]},
        store=store, schema="# Table: v_course_info", chat=chat, run=run,
        validate=lambda sql, requested_student_id=None: {"ok": True, "reason": None},
        expand=lambda sql: sql, exclude=lambda sql, sid: sql, settings=kw.get("settings", settings()),
    )


def test_majority_answer_and_response_shape():
    answers = iter(["SELECT COUNT(*) FROM v_course_info", "SELECT 2 FROM v_course_info", "SELECT COUNT(*) FROM v_course_info"])
    seen = []

    def chat(messages, *, model, temperature, seed=None):
        seen.append(messages)
        return next(answers)

    def run(sql, params, timeout_ms):
        return [{"n": 1}] if "COUNT" in sql else [{"n": 2}]

    result = run_v2("컴퓨터융합학부 과목 수", deps=deps(chat, run))

    assert result["data"] == [{"n": 1}] and result["error"] is None and result["rejected"] is False
    assert len(result["candidates"]) == 3 and result["cache_hit"] is False
    assert result["value_candidates"] == [{"column": "dept_name", "value": "공과대학 컴퓨터융합학부", "source": "ngram"}]
    assert any(m["content"] == "질문: 예시" for m in seen[0])


def test_hints_replace_value_search():
    captured = []

    def chat(messages, *, model, temperature, seed=None):
        captured.append(messages[-1]["content"])
        return "UNKNOWN"

    result = run_v2("q", value_hints=[{"column": "category", "value": "전공(핵심)"}], deps=deps(chat, lambda *a: []))

    assert "category = '전공(핵심)'" in captured[0] and "dept_name" not in captured[0]
    assert result["rejected"] is True and result["error"] == "질문이 모호합니다."


def test_retry_when_all_candidates_empty():
    replies = iter(["SELECT a FROM v_course_info"] * 3 + ["SELECT b FROM v_course_info"])

    def chat(messages, *, model, temperature, seed=None):
        return next(replies)

    # 두 SQL 모두 표준 컬럼으로 정규화되므로 결과는 계속 0행이다 — 재시도 후보가 추가되는지만 본다.
    result = run_v2("q", deps=deps(chat, lambda sql, p, t: []))

    assert len(result["candidates"]) == 4
    assert result["data"] == [] and result["error"] is None


def test_errors_everywhere_return_error_response():
    def chat(messages, *, model, temperature, seed=None):
        raise RuntimeError("down")

    result = run_v2("q", deps=deps(chat, lambda *a: []))

    assert result["data"] == [] and result["error"] and result["rejected"] is False
```

`generate_candidates`는 스레드로 병렬 호출하므로 가짜 `chat`의 응답 순서는 후보 index와 무관하다 — 테스트는 순서에 기대지 않게 짜여 있다. 재시도의 `deps.chat` 호출도 예외를 잡아 None으로 처리해야 `test_errors_everywhere_return_error_response`가 통과한다.

`backend/eval/test_run_eval.py`에 추가:

```python
def test_v2_is_registered_and_accepts_hints():
    assert "v2" in run_eval.PIPELINES
    assert getattr(run_eval.PIPELINES["v2"], "accepts_value_hints", False) is True
```

- [ ] **Step 2: 실패 확인**, **Step 3: 구현** — 위 흐름대로 `backend/t2s/pipeline.py` 작성. run_eval:

```python
def v2_pipeline(query, *, exclude_completed_courses=False, student_id=None, value_hints=None):
    from ..t2s.pipeline import run_v2

    return run_v2(query, exclude_completed_courses=exclude_completed_courses,
                  student_id=student_id, value_hints=value_hints)


v2_pipeline.accepts_value_hints = True
PIPELINES["v2"] = v2_pipeline
```

run_eval `main()`에서 캐시 비활성화와 같은 위치에 `os.environ.setdefault("T2S_REVIEW_LOG", "0")`(평가가 검토 로그를 오염시키지 않게), `collect_config`의 env 스냅샷은 이미 `T2S_*`를 포함한다.

`backend/main.py`의 `_run_query`: `if os.getenv("T2S_PIPELINE", "v1").strip().lower() == "v2":`이면 `from .t2s.pipeline import run_v2`로 `run_v2(req.query, exclude_completed_courses=..., student_id=student_no)`, 아니면 기존 `process(...)`. (기존 인증 로직은 그대로.)

- [ ] **Step 4: 통과 확인** — 전체 스위트.
- [ ] **Step 5: 커밋** — `feat: assemble the v2 pipeline and wire it into eval and the API`

---

### Task 12: 집계+요일·시간 평가 케이스 (spec 부록)

**Files:** Modify `backend/eval/golden_queries.json`, `backend/eval/test_golden_queries.py`(목표 수), `backend/eval/README.md`

- `enrollment_aggregate_36`~`_41` 6개 추가: 요일·시간 조건이 붙은 개수·최대 질의(예: "컴융 목요일 수업 분반 몇 개야", "오전 수업 중 정원이 가장 많은 분반"). 정답 SQL은 `COUNT(DISTINCT subject_code || '-' || section) AS course_count` 등 계획 A 관례대로, 동점 없음 확인, notes에 행 수.
- 목표 수 테스트의 `enrollment_aggregate`를 41로, README의 구성 표와 "알려진 주의사항 5"(집계+요일·시간 미지원)를 "v2에서 해결, 케이스 추가"로 갱신.
- `python -m backend.eval.validate_golden`(ERROR 0) 후 커밋 `test: add aggregate golden cases with day and time filters`.

---

### Task 13 (수동, 사용자·컨트롤러): v2 측정

서브에이전트에 맡기지 않는다(원격 Ollama 사용).

- [ ] **Step 1:** 원격 Ollama에 범용 코더 모델 준비: `ollama pull qwen2.5-coder:7b-instruct` (계획 C의 정식 비교 전 임시 기준).
- [ ] **Step 2:** v1 재측정(검증기 변경 반영): `python -m backend.eval.run_eval --pipeline v1`.
- [ ] **Step 3:** v2 측정 — 기존 모델과 범용 모델 각각: `T2S_MODEL=text2sql-local python -m backend.eval.run_eval --pipeline v2`, `T2S_MODEL=qwen2.5-coder:7b-instruct python -m backend.eval.run_eval --pipeline v2`, 그리고 `--decoupled`.
- [ ] **Step 4:** 기여도: `T2S_CANDIDATES=1`, `T2S_USE_EXAMPLES=0`, `T2S_VALUE_SOURCES=ner` / `ngram` 각각.
- [ ] **Step 5:** 결과 표를 사용자에게 보고하고 계획 C(모델 선정)로 넘어간다.
