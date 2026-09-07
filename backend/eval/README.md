# Text-to-SQL 골든 평가셋

`backend/process.py`의 전체 파이프라인(NER 교정 → 벡터 캐시 조회 → LLM 생성 → 검증 → DB 실행 → 자기수정 재시도)을
실제 Postgres/Ollama에 대해 실행해 정확도를 측정하는 회귀 평가 도구다.

## 실행 방법

저장소 루트에서 (반드시 `backend/.env`에 `DATABASE_URL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`이 설정돼 있어야 함):

```bash
python -m backend.eval.run_eval
```

DB/Ollama 없이 채점 로직 자체(37개 단위 테스트)만 검증하려면:

```bash
python -m pytest backend/eval/ -v
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
2. **`enrollment_aggregate`의 개수 세기 케이스**: `v_course_info`는 `course_schedule`/`course_prerequisite`와의
   JOIN으로 같은 과목이 여러 행으로 중복될 수 있다. `prompt.py`가 이 사실을 모델에게 알려주지 않으므로,
   모델이 `COUNT(*)`를 그대로 쓰면 중복 집계로 오답이 된다. 추가로, `COUNT(*)`는 별칭이 없어 컬럼명이
   `count`가 되는데 `reference_sql`은 `course_count`로 별칭을 지정해서, 값이 우연히 같더라도 컬럼명이
   달라 `compare_execution`의 공통 컬럼 비교에서 걸러진다 — 이는 집계 케이스에서 별칭 관례가 갈리면 항상
   나타나는 채점 특성이다.
3. **`course_filter`의 요일/시간 필터 케이스 일부(실제 실행 후 발견)**: `backend/process.py`의
   `expand_schedule_filtered_course_rows`는 WHERE 절에 `day_of_week`/`start_time`/`end_time`/`classroom`
   필터가 있으면, 해당 조건으로 먼저 (subject_code, section)만 찾은 뒤 **그 과목의 모든 스케줄 행**을
   다시 JOIN해서 반환하도록 의도적으로 설계돼 있다(예: "목요일 수업" 질의라도 매칭된 과목이 화요일에도
   수업이 있으면 화요일 행도 함께 돌려준다). 첫 실제 실행에서 `course_filter_01/04/05/10/11/12`가
   "추가된 행"으로 실패한 것은 대부분 모델이 틀려서가 아니라, 이 골든셋의 `reference_sql`이 이 확장
   동작을 반영하지 않고 해당 요일/시간의 행만 필터링했기 때문이다. 즉 이 6개 케이스의 `reference_sql`은
   `expand_schedule_filtered_course_rows`와 동일한 형태(매칭 과목 전체 스케줄을 반환)로 다시 작성해야
   정확한 측정이 된다. 이 항목은 파이프라인 버그가 아니라 골든셋 `reference_sql`을 다시 작성해야 하는 별도의 후속 작업이다. (`course_filter_06/09`의 실패는
   이와 무관한 별개의 원인 — `dept_name`/`subject_name`에 LIKE 대신 `=`를 쓰거나, NER 교정이 다른
   과목명으로 바꿔치기한 경우 — 이며, `course_filter_14`의 실패는 또 다른 별개의 원인 — `target_year` 대신
   `course_year`를 쓴 경우(`course_filter_08`과 동일한 종류의 혼동으로, 골든셋이 `target_year` 미문서화
   이슈를 검증하려고 의도적으로 설계한 케이스) — 이므로 이 세 케이스는 실제 정확도 이슈로 봐도 된다.)
4. **단일 컬럼 프로젝션에서의 `compare_execution` 관대함 (실행 비교 채점기 자체의 한계)**: `compare_execution`은
   reference와 generated 양쪽에 모두 존재하는 컬럼만 골라 비교하는 컬럼 교집합 방식을 쓴다. 모델이
   `prompt.py`의 지시(항상 19개 컬럼 전체를 SELECT)를 따르지 않고 `SELECT subject_name`처럼 컬럼 1개만
   프로젝션하는 경우가 실제로 흔한데, 이때는 "두 결과가 같은가"라는 비교가 사실상 "두 단일 컬럼 값 집합이
   겹치는가"로 퇴화해 버려서, 원래라면 걸러져야 할 오답이 통과(false pass)할 수 있다. 실제 라이브 실행에서
   확인된 사례:
   - `course_filter_08`: 정답이 써야 하는 `target_year = 2` 대신 `course_year = 2`를 쓴, 이 케이스가 원래
     잡아내려던 바로 그 버그를 저질렀는데도 PASS 처리됨 — 두 쿼리의 `subject_name` 집합이 우연히
     겹쳤기 때문.
   - `prerequisite_03`: reference는 `자료구조및실습`까지 포함하도록 `LIKE '%자료구조%'`로 작성됐지만,
     모델이 `subject_name = '자료구조'`로 정확히 일치시켜도 단일 컬럼 비교로는 차이를 구분하지 못해 PASS.
   - `prerequisite_05`: 올바른 컬럼 `prereq_subject_names = '없음'` 대신 잘못된 컬럼
     `prereq_subject_codes LIKE '%없음%'`으로 필터링했는데도 PASS.
   - `course_filter_07`: reference에 있는 `capacity > 0` 가드 조건을 조용히 빠뜨렸는데도 PASS.

   즉 이 관대함은 `course_filter`, `prerequisite` 같은 카테고리의 정확도를 실제보다 **과대평가**하는
   방향으로 작동한다 — 항목 1~3과는 반대 방향이다. 이는 채점기 설계상의 트레이드오프(컬럼이 일부만
   겹쳐도 정답으로 인정해 공정성을 확보하려던 의도가, 좁은 프로젝션 SQL에서는 역효과를 내는 것)이지
   파이프라인 버그가 아니므로, `compare_execution`의 비교 로직 자체는 이번 작업에서 바꾸지 않는다.

위 항목들은 이번 작업 범위에서 고치지 않는다(스펙 문서의 Out of scope 참고). 다음 반복에서 프롬프트/검증
로직을 수정할 때 우선순위를 정하는 데 이 평가셋의 카테고리별 정확도를 근거로 사용한다.

## 케이스 추가하기

`backend/eval/golden_queries.json`에 객체를 추가한다. 필수 키는
`backend/eval/test_golden_queries.py`의 `REQUIRED_KEYS`를 참고. 추가 후
`python -m pytest backend/eval/test_golden_queries.py`로 스키마를 검증한다.

`execution` 케이스를 추가할 때는 반드시 `reference_sql`을 실제 DB에 대해 직접 실행해 행 수가
의도한 대로 나오는지 확인한 뒤에 커밋한다(우연히 0행이 나오는 케이스는 채점 변별력이 없다).
