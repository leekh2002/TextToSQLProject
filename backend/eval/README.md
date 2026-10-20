# Text-to-SQL 골든 평가셋

`backend/process.py`의 전체 파이프라인(NER 교정 → 벡터 캐시 조회 → LLM 생성 → 검증 → DB 실행 → 자기수정 재시도)을
실제 Postgres/Ollama에 대해 실행해 정확도를 측정하는 회귀 평가 도구다.

## 실행 방법

저장소 루트에서 (반드시 `backend/.env`에 `DATABASE_URL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`이 설정돼 있어야 함):

```bash
python -m backend.eval.run_eval
```

DB/Ollama 없이 채점 로직과 평가셋 형식(단위 테스트)만 검증하려면:

```bash
python -m pytest backend/eval/ -v
```

옵션:
- `--filter <문자열>`: category 이름에 이 문자열이 포함된 케이스만 실행 (예: `--filter course_filter`)
- `--min-accuracy <0-100>`: 전체 정확도가 이 값 미만이면 종료 코드 1 반환
- `--report-dir <경로>`: JSON 리포트 저장 위치 (기본값 `backend/eval/reports/`)
- `--pipeline <이름>`: 평가할 파이프라인 (기본값 `v1` = 기존 `process()`). 새 파이프라인은
  `run_eval.PIPELINES`에 등록한다(계약은 아래 "파이프라인 계약").
- `--decoupled`: 케이스의 `gold_values`를 `value_hints`로 주입해 값 교정(NER/DB 조회) 오류를 제외하고
  SQL 생성 단계만 평가한다. 파이프라인이 `accepts_value_hints = False`이면(`v1`이 그렇다) 의미 없는 실행이므로
  종료 코드 2로 거부한다.
- `--use-cache`: 벡터 캐시를 켠 채로 평가한다. **기본값은 캐시 끔**: `main()`이 파이프라인을 부르기 전에
  `VECTOR_CACHE_ENABLED=0`을 설정한다. 캐시가 켜져 있으면 이전 실행(또는 이전 케이스)의 답을 재생할 뿐
  생성 성능을 측정하지 못하기 때문이다. 각 레코드에는 `cache_hit`(파이프라인이 주지 않으면 `null`)가 남는다.

### 파이프라인 계약

`pipeline(query, *, exclude_completed_courses=False, student_id=None, value_hints=None) -> dict`

- 반환 dict는 `process()`와 같은 키(`sql`, `data`, `error`, 선택적으로 `cache_hit`)를 갖고, 추가로 선택 키
  `rejected: bool`을 둔다. **`rejected: true`는 파이프라인이 질의를 의도적으로 거부했다는 뜻**이다(모호/답할 수 없음,
  또는 안전 규칙 위반). `expects_error` 케이스는 `rejected`가 `true`일 때만 통과하고, 그 밖의 오류(DB 오류, 타임아웃 등)는
  `reject_missed`로 실패한다.
- `v1` 어댑터는 `process()`의 `error`가 `"질문이 모호합니다."`(UNKNOWN)이거나 `backend/validate.py`의 안전 거부 사유
  (SELECT 전용, 여러 문장, 금지 키워드, 허용되지 않은 테이블, student 컬럼/필터 전용, student·enrollment 학번 스코프)와
  일치하면 `rejected: true`를 붙인다. `process()`가 그 사유로 예외를 던져도 같은 결과로 바꾼다. "FROM 또는 JOIN 절이 필요합니다.",
  "기본 LIMIT가 필요합니다."는 잘못된 SQL이지 거부가 아니므로 제외한다. 사유 문구가 바뀌면
  `test_rejection_patterns_track_validate_reasons`가 실패한다.
- `value_hints`: `None`이면 파이프라인이 값 검색을 스스로 한다. 리스트(빈 리스트 `[]` 포함)이면 "정확히 이 힌트만 쓴다"는 뜻이다.
  `--decoupled`일 때만 케이스의 `gold_values`가 그대로 전달된다.
- 각 파이프라인은 함수 속성 `accepts_value_hints`(bool)를 선언한다. 없으면 `False`로 본다.

평가셋을 DB에 대해 점검하려면(정답 SQL 실행, 빈 정답 표시, 필드 형식, id/질의 중복, `LIKE` 조건과 `gold_values`의 일치,
행 수 상한):

```bash
python -m backend.eval.validate_golden
```

문제가 있으면 `ERROR ...` 줄을 출력하고 종료 코드 1을 반환한다(경고는 `WARN`). 케이스를 추가·수정할 때마다 실행한다.

- ERROR: `reference_sql`에서 `컬럼 LIKE '%kw%'`(`NOT LIKE` 제외)로 거르는 컬럼의 `gold_values` 항목이, `kw`가 DB(`v_course_info`의
  DISTINCT 값, 읽기 전용 조회)에서 값 하나로만 특정될 때의 그 값과 다르면 오류다. `kw`가 여러 값에 걸리면 그 항목은 빼야 한다.
- WARN: 확장된 정답 결과가 `T2S_ROW_CAP`(기본 50)행보다 많으면 경고한다. 생성 SQL은 `LIMIT 50`으로 잘리므로 이런 케이스는
  아래 ROW_CAP 규칙으로 채점된다. 정답 결과가 스케줄 확장 상한(200행)과 정확히 같으면 정답 자체가 잘렸을 수 있으므로 따로 경고한다.

## 평가셋 구성 (238개)

| category | 개수 |
| --- | --- |
| `course_filter` | 80 |
| `prerequisite` | 30 |
| `enrollment_aggregate` | 35 |
| `personalized_lookup` | 30 |
| `exclude_completed_courses` | 30 |
| `ambiguous_reject` | 30 |
| `graduation_requirement` | 3 (이번 범위 밖이라 확장하지 않음) |

이 분포는 `test_golden_queries.py::test_category_counts_match_the_expanded_design`이 고정한다.
`ambiguous_reject`는 스키마에 없는 정보(7), 다른/전체 학생 개인정보(6), 쓰기 요청(5),
지시 대명사만 있는 질의(4), 서비스와 무관한 질의(3)와 기존 5건(날씨, 수강신청 일정, 전화번호, 1학년 명단, 삭제)으로 구성된다.

## 리포트 항목

`run_eval`이 출력하고 JSON 리포트(`config`, `summary`, `records`)에 저장하는 항목:

- 카테고리별 정확도: 정답 결과가 0행인 케이스(`empty_gold: true`)는 헤드라인 정확도에서 빼고 "빈 정답(별도)"으로 따로 보고한다.
- 실패 유형(`failure_types`): `ok`, `reject_missed`(거부돼야 하는데 SQL이 나옴), `error`, `structural_mismatch`,
  `empty_result`, `result_mismatch`, `exception`.
- 실패 유형에는 `infra_error`(정답 SQL 실행 실패 — DB 연결 등 평가 인프라 문제)도 있다.
- 응답 시간 p50/p95(ms): **첫 케이스는 NER/KURE/모델 로딩이 포함된 워밍업이라 백분위수에서 뺀다**
  (`latency_ms.warmup_excluded_ms`에 따로 기록).
- 평균 Soft-F1: 결과 행 단위 F1. 실행 채점과 같은 컬럼 매칭과 집합(중복 제거) 의미를 쓴다. 통과/실패와 별개로
  "얼마나 가까웠는지"를 본다. 실행 채점 케이스가 오류·예외로 결과를 못 내면 0.0으로 기록한다(빠지지 않는다).
- `config`: 파이프라인 이름, `--decoupled` 여부, `hints_used`(힌트가 실제로 전달됐는지), `--filter` 값, git SHA
  (`git rev-parse --short HEAD`, 없으면 `null`), 평가셋 파일의 sha256과 케이스 수, `T2S_*`·`VECTOR_CACHE_*` 환경변수,
  `OLLAMA_MODEL`, `OLLAMA_BASE_URL`. 리포트끼리 비교할 때 조건을 확인하는 용도다.

## 채점 방식

- `grading: "execution"` — `reference_sql`과 파이프라인이 생성한 SQL을 둘 다 실제 DB에 실행해 결과 행을
  순서 무관 집합으로 비교한다. 문법이 달라도 결과가 같으면 정답으로 처리한다. 개인화 조회(`personalized_lookup`)도
  학번 `202102671`로 고정된 정답 SQL을 실행해 이 방식으로 채점한다. 다음 규칙이 적용된다:
  1. **스케줄 확장 적용**: 파이프라인은 요일/시간/강의실 필터가 있으면 `expand_schedule_filtered_course_rows`로
     매칭된 과목의 모든 스케줄 행을 돌려준다. 정답 SQL에도 같은 확장(`expand_reference_sql`)을 적용해 비교한다.
  2. **컬럼 매칭**: 정답의 각 컬럼을 생성 결과의 같은 이름 컬럼과 짝짓고, 없으면 아직 짝이 없는 생성 컬럼 중 값의
     다중집합(전체 행에 걸친 값 `Counter`)이 같은 컬럼과 짝짓는다. 그래서 `COUNT(*) AS count`도 값이 맞으면 `course_count`
     자리를 채우지만, 값이 틀리면(예: `count = 99`) 짝이 없어 실패한다. 짝을 못 찾은 정답 컬럼이 하나라도 있으면 실패하고,
     생성 결과의 남는 컬럼은 무시한다. 행 비교는 짝지은 컬럼 쌍에 대해 집합으로 한다.
  3. **식별 컬럼 규칙**: 정답 결과에 `subject_code`·`section`이 있으면 생성 결과에도 같은 이름으로 있어야 한다.
     `SELECT subject_name`처럼 좁게 프로젝션해 우연히 겹치는 것만으로 통과하는 일을 막는다.
  4. **ROW_CAP 규칙(잘렸지만 정답)**: 파이프라인은 생성 SQL에 `LIMIT 50`을 붙인다. 생성 결과가 정확히 `T2S_ROW_CAP`(기본 50,
     호출 시점에 읽음)행이고 그 행이 모두 정답 집합에 들어 있으면 통과다(`order_sensitive` 케이스는 정답의 앞부분과 순서까지 같아야 한다).
  5. **학생 범위**: 케이스에 `student_id`가 있고 생성 SQL이 `student`나 `enrollment`를 참조하면, 참조한 테이블마다
     `backend.validate.has_scoped_student_filter`(학번 리터럴 또는 플레이스홀더 허용)를 통과해야 한다. 아니면 "학생 범위 미지정"으로 실패한다.
     결과가 우연히 같아도 다른 학생 데이터를 읽을 수 있는 SQL은 정답이 아니다.
  6. **인프라 오류**: 정답 SQL 실행 자체가 실패하면 "정답 SQL 실행 실패: ..."로 기록하고 실패 유형은 `infra_error`다.
- `grading: "structural"` — 실행 결과 비교가 부적절한 케이스(졸업요건처럼 데이터가 없는 경우)용.
  생성된 SQL이 필요한 테이블/컬럼을 참조하는지, 학생 스코프가 걸렸는지만 검증한다.
- `expects_error: true` — 모호하거나 안전 정책상 거부돼야 하는 질의. 파이프라인 결과에 `rejected: true`가 있어야 정답이다
  (위 "파이프라인 계약"). 단순히 `error`가 있는 것만으로는 통과하지 않는다.

## 알려진 결과 해석 주의사항

이 평가셋을 처음 돌리면 다음과 같은 알려진 요인들로 인해 특정 카테고리/케이스의 정확도가 낮게 측정될 수 있다. **채점기 버그가 아니다.**

1. **`personalized_lookup`, `graduation_requirement`의 검증 갭 (실재하지만 이번 실행에서는 드러나지 않음)**:
   `backend/process.py`는 `exclude_completed_courses=True`일 때만 `student_id`를 SQL 검증의
   `requested_student_id`로 전달한다(`validate_sql` 호출부 참고). 일반 개인화 조회
   (`exclude_completed_courses=False`)에서는 생성된 SQL이 올바르게 `student.student_id = '202102671'`로
   스코프돼도 검증 단계(`backend/validate.py`의 `has_scoped_student_filter`)가 플레이스홀더(`:student_id` 등)만
   허용하므로 거의 항상 실패한다 — 이는 코드로 확인되는 실제 파이프라인 갭이다. 다만 실제 라이브 실행
   리포트(`backend/eval/reports/*.json`)를 확인해 보면, 이 두 카테고리에서 발생한 8건의 실패 중 이 검증
   갭이 원인이 된 사례는 하나도 없었다: `personalized_lookup_01/02/05`는 모델이 아예 `student` 테이블을
   참조하지 않아 "필요한 테이블이 SQL에 없습니다: student"로 실패했고, `personalized_lookup_03/04`는 존재하지
   않는 컬럼 참조 등 원시 Postgres 오류로 실패했으며, `graduation_requirement_01/02/03`은
   `required_subject` 테이블을 아예 참조하지 않아 실패했다. 즉 이 검증 갭은 실재하지만, 모델이 그 지점에
   도달하기도 전에 이미 다른 이유로 실패하고 있어서 이번 실행 결과로는 아직 정량화되지 않았다.
   (이 분석은 개인화 조회를 structural로 채점하던 이전 실행 기준이다. 지금 `personalized_lookup`은 학번을 고정한 정답 SQL로
   execution 채점한다.)
2. **`enrollment_aggregate`의 개수 세기 케이스**: `v_course_info`는 `course_schedule`/`course_prerequisite`와의
   JOIN으로 같은 과목이 여러 행으로 중복될 수 있다. `prompt.py`가 이 사실을 모델에게 알려주지 않으므로,
   모델이 `COUNT(*)`를 그대로 쓰면 중복 집계로 오답이 된다. 별칭이 달라도(`count` vs `course_count`) 값이 같으면
   컬럼 매칭으로 통과하고, 값이 다르면 실패한다.
3. **(해소됨) `course_filter`의 요일/시간 필터 케이스와 스케줄 확장**: 예전에는 `reference_sql`이 확장 동작을 반영하지
   않아 `course_filter_01/04/05/10/11/12` 등이 "추가된 행"으로 실패했다. 지금은 정답 SQL에도 스케줄 확장을 적용하므로
   이 원인의 오탐은 없다. (`course_filter_06/09/14`는 이것과 무관한 실제 정확도 이슈다.)
4. **(해소됨) `compare_execution`의 컬럼 교집합 관대함**: 예전에는 이름이 같은 컬럼만 교집합으로 비교해서, 정답 컬럼이
   빠지거나 별칭이 다른 집계값(`count = 99`)이 비교에서 빠진 채 통과할 수 있었다. 지금은 모든 정답 컬럼이 이름 또는 값으로
   짝지어져야 한다(위 "컬럼 매칭").
5. **알려진 파이프라인 한계(다음 계획 대상)**: 스케줄 확장은 요일/시간 필터가 걸린 쿼리를 무조건 과목 행 목록으로
   바꾼다. 그래서 `COUNT`/`GROUP BY` 같은 집계에 요일·시간 조건이 붙으면(예: "월요일 수업 개수") 집계값 대신 행 목록이
   반환된다. 이 때문에 현재 평가셋에는 집계 + 요일/시간 조합 케이스가 없다. 파이프라인이 집계를 확장에서 제외하도록
   바뀌면 그때 이 조합 케이스를 추가한다.

위 항목들은 이번 작업 범위에서 고치지 않는다(스펙 문서의 Out of scope 참고). 다음 반복에서 프롬프트/검증
로직을 수정할 때 우선순위를 정하는 데 이 평가셋의 카테고리별 정확도를 근거로 사용한다.

## 케이스 추가하기

`backend/eval/golden_queries.json`에 객체를 추가한다. 필수 키는 `backend/eval/test_golden_queries.py`의
`REQUIRED_KEYS`를 참고. 선택 필드:

- `gold_values`: `[{"column": "dept_name", "value": "공과대학 컴퓨터융합학부"}, ...]`. `--decoupled`가 값 힌트로 주입한다.
  `column`/`value`는 모두 문자열이다. 정답 조건 중 **질문에 드러난 문자열 값 조건만** 적고(숫자 `target_year = 3`, 시간 `start_time`, `<>` 조건 제외),
  값이 없는 질의는 `[]`. `value`는 DB에 실제로 있는 정확한 문자열이어야 한다. `LIKE` 조건이 DB에서 값 하나로 특정되면 그 실제 DB 값
  (예: `공과대학 컴퓨터융합학부`)을 쓰고, 키워드가 여러 값에 걸리면(예: `%알고리즘%`, `%자료구조%`처럼 콤마로 이어진 선수과목 목록 포함)
  그 조건은 `gold_values`에서 뺀다(키워드 자체를 쓰지 않는다). `validate_golden`이 이 규칙을 ERROR로 검사한다.
  "내 학과"처럼 학생 정보에서 유도되는 값은 질문에 없으므로 넣지 않는다. reject·졸업요건 케이스는 항상 `[]`.
- `empty_gold`: 정답 결과가 0행인 케이스에만 `true`. 0행인데 `empty_gold`가 없으면 `validate_golden`이 ERROR로 잡는다.

작성 규칙:

1. **형식**: 모든 키를 채운다(`structural_checks`는 execution이면 `null`, reject면 `{}`). id는 두 자리 번호
   (`course_filter_07`)이고 중복 불가, 질의 문자열도 중복 불가. 실행 채점 케이스는 `gold_values`를 반드시 둔다
   (값 조건이 없거나 모두 여러 값에 걸리는 키워드라면 `[]`도 된다).
   `reference_sql`은 실제 DB에 직접 실행해 행 수를 확인하고 `notes`에 적는다. 이때 행 수는 **스케줄 확장 이후** 기준이다.
   학생 케이스는 DB에 이수 내역이 있는 `202102671`만 쓴다. 이 학생은 `공과대학 컴퓨터인공지능학부` 개설 과목(4개)을 모두
   이수했으므로 이 학부는 `exclude_completed_courses` 케이스에 쓸 수 없다(제외 후 항상 0행).
2. **gold_values**: 위 설명대로 문자열 조건만. 학과는 정확히 하나로 특정되도록 쓴다.
3. **정답 SQL 관례**: 학과 키워드가 형제 학과와 겹치면 단과대를 붙여 한정한다(`'%경상대학 경제학과%'`, `'%자연과학대학 화학과%'`).
   `credit_hours`는 `'3/3/0'` 꼴이라 `LIKE '3/%'`로 거른다. 여석은 `enrolled < capacity AND capacity > 0`.
   교필(교양 필수)은 `category LIKE '%교양(소양필수)%'`. 과목 수는 `COUNT(DISTINCT subject_code || '-' || section) AS course_count`
   (`v_course_info`가 스케줄 JOIN으로 행이 중복되므로 `COUNT(*)`를 쓰지 않고, 별칭도 `course_count`로 통일).
4. **변형 표현**: 케이스의 40% 이상은 구어체·줄임말·어순 변형(예: "컴융", "~뭐있어")으로 쓴다. 같은 정답 SQL(참조)을
   공유하는 질의는 3개 이하로 제한한다.
5. **변별력**: 우연히 0행이 나오는 케이스는 채점 변별력이 없으므로 쓰지 않는다. 포함/제외 조건 수를 카테고리 안에서 고르게 분배한다.
6. **모호함 금지**: 한 질의가 두 해석으로 갈리는 표현을 피한다(예: "정원 초과"와 "마감"을 섞어 쓰지 않는다).
7. **금지 사항**: DB에 없는 값, "이번 주", "오늘", "다음 학기" 같은 시간 상대 표현, 의도가 모호한 질의를 답이 있는 카테고리에 넣지 않는다.
   모호함·거부는 `ambiguous_reject`에서만 다루며, 거기서도 질의는 "스키마에 없음/금지된 요청"으로 명확히 거부돼야 하고
   `v_course_info`로 답할 수 있는 경계 사례여서는 안 된다.

`ambiguous_reject` 케이스는 `grading: "structural"`, `expects_error: true`, `reference_sql: null`, `structural_checks: {}`,
`gold_values: []`로 쓴다. 유형(스키마에 없는 정보 / 타 학생·전체 학생 개인정보 / 쓰기 요청 / 지시 대명사만 있는 질의 /
서비스와 무관한 질의)을 고르게 유지한다.

추가 후 `python -m backend.eval.validate_golden`과 `python -m pytest backend/eval -q`를 실행한다.
`golden_queries.json`은 UTF-8, 한글 그대로, 들여쓰기 2칸, CRLF로 저장한다.
