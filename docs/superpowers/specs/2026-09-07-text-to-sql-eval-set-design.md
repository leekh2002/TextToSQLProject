# Text-to-SQL 골든 평가셋 설계

## 배경 및 목적

현재 서비스에는 text-to-sql 파이프라인(`backend/process.py` → `keyword_extract.py` → `llm.py` → `validate.py`)의 정확도를 정량적으로 측정할 수단이 없다. `backend/test_correction.py`는 NER 교정 로직에 대한 단위 테스트일 뿐, 자연어 질의 → SQL 생성 → 실행 결과 전체를 검증하지 않는다.

이전 구조 분석에서 확인한 정확도 개선 후보(프롬프트의 스키마 커버리지 누락, few-shot 부재, 벡터 캐시 오매칭 위험, 자기수정 재시도 한도 등)를 실제로 검증하려면, 먼저 회귀 없이 반복 측정 가능한 골든 평가셋과 실행기가 필요하다. 이 문서는 그 평가셋과 실행기의 설계를 다룬다.

## 환경 확인 결과 (2026-09-07 기준)

- Postgres(`DATABASE_URL=postgresql://postgres:***@localhost:5432/postgres`) 연결 가능, 실데이터 존재:
  - `v_course_info` 6846행, `student` 1행(`202102671`, `dept_code=D094`, `grade=4`), `enrollment` 29행, `course_prerequisite` 30행, `required_subject` **0행**
- Ollama(`OLLAMA_BASE_URL`, 모델 `text2sql-local`, Qwen2.5-Coder-7B Q4_K_M) 원격 연결 가능
- Redis(`REDIS_URL=redis://localhost:6379/0`) 로컬에서 연결 불가 → 벡터 캐시는 항상 미스로 동작. 평가 재현성 측면에서는 오히려 유리(캐시 히트로 인한 비결정성 배제)하므로 별도 우회 로직 없이 현재 상태를 그대로 이용한다.
- `required_subject`가 비어 있고 `student`가 1건뿐이므로, 이 영역과 개인화 조회는 실행 결과 비교 대신 SQL 구조 검증으로 채점한다.

## 채점 방식

케이스마다 `grading` 필드로 지정한다.

### 1. `execution` (기본, 표준 text-to-sql 벤치마크 방식)
- `reference_sql`(사람이 작성한 정답 SQL)과 파이프라인이 생성한 실행용 SQL을 각각 실제 DB에 실행.
- 기본은 결과 row를 **순서 무관 집합**으로 비교(`set(tuple(row.items()) for row in rows)`와 유사). 문법이 달라도 결과가 같으면 정답 처리.
- `order_sensitive: true`인 케이스만 순서까지 비교(리스트 그대로 비교).
- DB 실행 자체가 에러(문법 오류 등)이면 오답 처리.

### 2. `structural` (실행 비교가 부적절한 케이스)
- 대상: 졸업요건(`required_subject`, 데이터 0건), 개인화 조회(학생 1명뿐이라 결과 비교의 판별력이 낮음).
- sqlglot로 생성 SQL을 파싱해 케이스별 체크리스트를 검증한다. 체크리스트 예:
  - 반드시 참조해야 하는 테이블 집합 (`required_tables: ["required_subject", "student"]`)
  - 반드시 존재해야 하는 컬럼 참조 (`required_columns: ["required_subject.subject_code"]`)
  - `student_id`가 요청된 학생 값(또는 플레이스홀더)으로 스코프됐는지
- 범용 AST 동등성 엔진은 만들지 않는다. 케이스별로 필요한 조건만 최소한으로 명시한다.

### 3. `expects_error: true` (모호한 질의)
- `process()` 결과가 `{"error": ...}` 형태여야 정답. 그 외 정상 SQL이 생성되면 오답.

## 골든 쿼리셋 구성

파일: `backend/eval/golden_queries.json` — 케이스 배열.

각 케이스 스키마:
```json
{
  "id": "string, 고유 식별자 (카테고리_순번)",
  "category": "string",
  "query": "자연어 질의",
  "grading": "execution | structural",
  "reference_sql": "grading=execution일 때만. 사람이 직접 작성/검증한 정답 SQL",
  "order_sensitive": false,
  "expects_error": false,
  "student_id": "202102671 | null",
  "exclude_completed_courses": false,
  "structural_checks": {
    "required_tables": ["..."],
    "required_columns": ["..."],
    "student_scoped": true
  },
  "notes": "왜 이 케이스가 필요한지, 무엇을 검증하는지"
}
```

카테고리와 목표 개수 (총 43개):

| 카테고리 | 개수 | grading | 비고 |
|---|---|---|---|
| `course_filter` | 15 | execution | 학과/이수구분/요일/시간/교수/학점/온오프라인 등 단일·복합 필터 |
| `exclude_completed_courses` | 5 | execution | 유일한 실제 학생(`202102671`)의 `enrollment` 29건 이용 |
| `prerequisite` | 5 | execution | `course_prerequisite` 30행 활용 |
| `enrollment_aggregate` | 5 | execution | 수강인원/정원 등 집계·비교 |
| `personalized_lookup` | 5 | structural | 학생 본인 학과/학년 등 조회. `student` 스코프 규칙 준수 여부 검증 |
| `graduation_requirement` | 3 | structural | `required_subject` 참조 여부만 검증(데이터 없음 감안) |
| `ambiguous_reject` | 5 | structural(`expects_error`) | 스키마 밖 요청, 지나치게 모호한 질의 등 |

각 `execution` 케이스의 `reference_sql`은 설계 승인 후 구현 단계에서 실제 DB에 대해 직접 실행/검산하여 작성한다(결과가 0행으로 나오는 게 우연인지 의도인지 확인 포함).

## 실행기 (`backend/eval/run_eval.py`)

- CLI: `python -m backend.eval.run_eval [--filter <category>] [--min-accuracy <0-100>] [--report-dir backend/eval/reports]`
- 각 케이스에 대해 `process(case["query"], exclude_completed_courses=case["exclude_completed_courses"], student_id=case["student_id"])`를 실제 호출(전체 파이프라인: NER 교정 → 캐시 조회 → LLM 생성 → 검증 → 실행 → 자기수정 재시도까지 그대로 탄다).
- `grading.py`의 `grade_case(case, result)` 로 정오 판정.
- 콘솔 출력: 카테고리별 정확도 표 + 전체 정확도.
- 실패 케이스는 `id`, `query`, `reference_sql`(있는 경우), 생성된 `sql`, 실패 사유(불일치 row diff 또는 미충족 구조 조건)를 콘솔과 JSON 리포트(`backend/eval/reports/<UTC 타임스탬프>.json`) 양쪽에 기록.
- `--min-accuracy` 지정 시 전체 정확도가 미달이면 non-zero exit code (추후 CI 연동 여지, 지금은 수동 실행 전용).

## 변경/신규 파일

모두 신규 파일이며 기존 파이프라인 코드(`process.py`, `llm.py`, `validate.py` 등)는 수정하지 않는다.

- `backend/eval/__init__.py`
- `backend/eval/golden_queries.json`
- `backend/eval/grading.py` — execution/structural 채점 로직
- `backend/eval/run_eval.py` — CLI 실행기
- `backend/eval/README.md` — 실행 방법, 리포트 해석법, 케이스 추가 가이드

## 검증 계획

1. 43개 케이스를 채운 뒤 `run_eval.py`를 한 번 실제 환경(Ollama+DB 연결)에서 실행.
2. 전체/카테고리별 정확도가 극단값(0% 또는 100%)으로 나오면 채점 로직 버그 가능성을 우선 의심하고 수동으로 몇 건 재현.
3. 실패 케이스 중 최소 3~5건은 사람이 직접 생성 SQL을 읽고 "실제로 틀렸는지" vs "채점기 버그인지" 확인.

## 범위 밖 (Out of scope)

- 이 작업에서 프롬프트/스키마/RAG/캐시 로직 자체를 수정하지 않는다. 평가셋과 실행기만 만든다.
- CI 파이프라인 연동(GitHub Actions 등)은 포함하지 않는다.
- `required_subject`용 실데이터 시딩은 하지 않는다(구조 검증으로 대체).
