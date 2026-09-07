# course-custom-ner 재학습 설계

## 배경 및 목적

`backend/keyword_extract.py`가 사용하는 커스텀 NER 모델(`backend/course_custom_ner_model/models/course-custom-ner`)은 다음 두 가지 문제를 보인다.

1. **개체명 경계(위치) 오류**: 조사가 span에 포함/제외되는 경계가 불안정하고, 실제 사용자 문장의 구조적 다양성(접속, 범위 표현, 수식어 등)에 취약하다.
2. **약어 보정 정확도 저하**: 이건 NER 모델이 아니라 `keyword_extract.py`의 후처리(`correct_ner_entities`/`find_best_db_match`) 문제로 별도 확인됨(`dataset_info.json`의 생성 노트: "The model still extracts raw spans only and performs no term correction.") — 이 문서는 **1번(모델 재학습)**만 다룬다. 2번(교정 로직 자체의 결함, 예: sequential-match 최저점 80 고정)은 이 작업 범위 밖이며 별도로 다룬다.

원본 학습 스크립트와 학습 데이터(`ner_train.jsonl`, `ner_valid.jsonl`, `ner_test.jsonl`, `ner_all.jsonl`)는 이 저장소/환경 어디에도 없다(`.gitignore`가 `backend/course_custom_ner_model/*`를 통째로 제외하고 메타데이터 일부만 `git add -f`로 커밋됨). 따라서 데이터부터 새로 만들어야 한다.

## 현재 상태 확인 (2026-09-07 기준)

- **모델 아키텍처**: `config.json` 기준 `architectures: ["ElectraForTokenClassification"]`, `embedding_size=128, hidden_size=256, num_hidden_layers=12, num_attention_heads=4, vocab_size=35000` — 공개 체크포인트 `monologg/koelectra-small-v3-discriminator`의 설정과 일치. 원본은 이 체크포인트에서 파인튜닝된 것으로 추정.
- **라벨 스키마(16개, BIO)**: CAPACITY, CATEGORY, CLASS_MODE, COURSE_NAME, COURSE_YEAR, CREDIT, DAY, DEPARTMENT, ENROLLED, EVAL_TYPE, GRADE_METHOD, PROFESSOR, ROOM, SECTION, TIME, VACANCY.
- **다운스트림 실사용 라벨**: `keyword_extract.py`의 `ENTITY_REFERENCE_MAP`(교정 로직 있음)은 CATEGORY, COURSE_NAME, DEPARTMENT, CLASS_MODE, EVAL_TYPE, GRADE_METHOD, PROFESSOR 7개만 다루고, `MASKABLE_ENTITY_LABELS`(벡터 캐시 마스킹)는 CATEGORY, COURSE_NAME, DAY, DEPARTMENT, TIME 5개만 다룬다. 합집합은 9개: **DEPARTMENT, CATEGORY, COURSE_NAME, PROFESSOR, CLASS_MODE, EVAL_TYPE, GRADE_METHOD, DAY, TIME**. 나머지 7개(CAPACITY, COURSE_YEAR, CREDIT, ENROLLED, ROOM, SECTION, VACANCY)는 추출은 되지만 후속 로직이 전혀 없다.
- **원본 학습 데이터 규모**: `metadata/dataset_info.json` 기준 원본(hand-authored) 277행(train) → 슬롯 재조합으로 5275행(train)까지 합성 증강. 이 좁은 원본 풀이 구조적 다양성 부족(경계 오류의 유력한 원인)으로 추정됨.
- **실제 사용자 질의 로그**: `backend-log.txt`(2912줄, 2026-05-13 ~ 현재)에 고유 질의 207개 확인. 접속("A랑 B"), 범위("1시~3시 사이"), 수식어("~에 진행하는"), 잔여석 표현("빈자리가 있는"/"잔여석이 남아있는"), 실제 약어("알응", "컴과사") 등 현재 합성 데이터에 없을 패턴이 다수 존재.
- **`COMMON_ALIASES`(keyword_extract.py) 검증**: 현재 CATEGORY 9개 별칭(전기/전핵/전심/교소/교소필/일선/교균/교기/교직)이 DB의 실제 CATEGORY 값 9개와 정확히 1:1 대응하며, 전부 "괄호/단어 단위로 쪼개 각 조각의 첫 음절을 딴다"는 동일 규칙으로 만들어져 있음이 확인됨 — 이 규칙을 프로그램으로 일반화할 수 있는 근거.

## 범위 결정 사항 (대화를 통해 확정)

- **데이터 소스**: 템플릿 기반 합성 생성(슬롯 채우기, LLM 자동 라벨링이나 실사용 로그 자동 라벨링은 채택 안 함).
- **라벨 우선순위**: 위 9개 실사용 라벨에 템플릿/슬롯 조합을 집중 배분. 나머지 7개는 완전히 빼지 않고 가볍게만 유지(다른 라벨과의 혼동 방지 목적).
- **약어 유추 대상**: **DEPARTMENT, CATEGORY, COURSE_NAME 3개만**. PROFESSOR는 약어 고려 안 함(요청에 따라 제외).
- **모델 아키텍처**: 동일한 KoELECTRA-Small 구조 유지, `monologg/koelectra-small-v3-discriminator`에서 처음부터 다시 파인튜닝(기존 `model.safetensors`에서 이어서 하지 않음 — 데이터 분포를 크게 바꾸는 상황이라 기존 편향을 물려받지 않기 위함).
- **학습 환경**: 이 머신이 아닌 별도 GPU 환경(원격)에서 실행 예정 — 즉 학습 스크립트는 이식 가능해야 하고(하드코딩된 로컬 경로 없이), 학습 산출물(체크포인트)은 학습 후 이 저장소의 `backend/course_custom_ner_model/models/course-custom-ner/`에 수동으로 옮겨오는 흐름(LLM `.gguf` 파일과 동일한 관례).

## 컴포넌트 설계

### 1. 약어 유추 파이프라인 (`backend/course_custom_ner_model/scripts/infer_abbreviations.py`)

**입력**: `keyword_extract.load_reference_values()`가 이미 구현한 방식대로 DB에서 DEPARTMENT, CATEGORY, COURSE_NAME의 전체 distinct 값을 가져온다(PROFESSOR는 조회하지 않음).

**처리**:
1. **어근 사전 자동 마이닝**: 각 라벨의 전체 값 목록을 대상으로, 반복 등장하는 2~4음절 부분 문자열을 빈도 기반으로 추출해 "의미 단위 후보" 사전을 만든다(사람이 손으로 어근 목록을 만들지 않음 — 사용자가 요청한 "모든 데이터를 참고"에 해당).
2. **접미어 제거**: DEPARTMENT는 "OO대학 " 접두어와 "학과/학부/전공" 등 접미어를 먼저 분리.
3. **분절 + 초성/초음절 결합**: 어근 사전과 대조해 값을 의미 단위로 분절하고, 각 단위의 첫 음절을 이어붙여 약어 후보를 생성(기존 `COMMON_ALIASES`가 검증한 규칙과 동일).
4. **후보 출력**: 값별로 생성된 약어 후보를 사람이 검토하기 쉬운 형태(예: CSV/JSON, `원본값, 후보약어, 라벨` 컬럼)로 `backend/course_custom_ner_model/metadata/abbreviation_candidates.json`에 저장. **이 스크립트는 자동 채택하지 않는다** — 사람이 한 번 훑어보고 말이 안 되는 후보를 걸러낸 결과(`abbreviation_candidates.reviewed.json` 같은 이름)를 다음 두 단계가 소비한다.

**소비처**:
- (a) `keyword_extract.py`의 `COMMON_ALIASES`를 검수된 약어로 확장(별도 작업으로 반영 — 이 문서 범위에 포함하되 구현 계획에서 별도 태스크로 분리).
- (b) 아래 2번 데이터 생성기의 약어 슬롯 값으로 사용.

### 2. 템플릿 기반 합성 데이터 생성기 (`backend/course_custom_ner_model/scripts/generate_ner_dataset.py`)

- 슬롯: DB에서 조회한 실제 값(부서명/카테고리/과목명/교수명/요일/시간 등) + 검수된 약어 후보(DEPARTMENT/CATEGORY/COURSE_NAME만).
- 템플릿 종류를 원본보다 크게 늘림: 기본 필터 조합, 접속("A랑 B"), 범위 표현, 제외/부정 표현, 수식어(잔여석/빈자리), 어미 다양화, 약어 혼용 문장. `backend-log.txt`에서 확인된 패턴을 템플릿 카탈로그의 근거로 삼는다.
- 슬롯 채우기 시점에 각 개체의 정확한 문자 오프셋을 알고 있으므로 BIO 라벨을 프로그램이 직접 계산 — 라벨 정확도는 100% 보장됨(사람이 손으로 라벨링할 필요 없음).
- 9개 실사용 라벨에 템플릿·슬롯 조합을 집중 배분, 나머지 7개는 최소 유지 비율로 포함.
- 출력: `ner_train.jsonl` / `ner_valid.jsonl` / `ner_test.jsonl`(원본과 동일한 파일명 관례) — **템플릿 단위로 train/valid/test를 분리**(같은 템플릿에서 나온 근접 중복 문장이 train과 test에 동시에 들어가 평가를 왜곡하는 것을 방지).
- 이 스크립트와 생성 결과는 기존 `.gitignore` 관례를 따른다: 스크립트(코드)는 커밋, 생성된 jsonl(데이터)은 커밋하지 않음 — 재현 가능한 파이프라인이므로 데이터 자체를 저장소에 둘 필요가 없다.

### 3. 실제 질의 홀드아웃 평가셋

- `backend-log.txt`의 고유 질의 207개 중 일부를 사람이 직접 정답 스팬으로 라벨링(학습에는 사용하지 않음, 평가 전용).
- 목적: "합성 템플릿에는 강한데 실제 문장엔 약하다"는 원본 모델의 문제를 재현하지 않도록, 학습에 전혀 쓰이지 않은 실문장으로 최종 검증.
- 저장 위치/형식은 2번 생성기의 jsonl과 동일한 스키마(토큰 또는 문자 오프셋 + BIO 라벨)로 맞춰서, 같은 평가 스크립트를 재사용할 수 있게 한다.

### 4. 학습 스크립트 (`backend/course_custom_ner_model/scripts/train.py`)

- HuggingFace `Trainer` 기반 표준 토큰분류 파인튜닝.
- 베이스 체크포인트: `monologg/koelectra-small-v3-discriminator`(공개 허브 모델, 하드코딩된 로컬 경로 없이 원격 GPU 환경에서 그대로 실행 가능).
- 라벨 스키마는 기존 `labels.json`과 동일하게 유지(16개 BIO 라벨) — 하위 호환을 위해 `id_to_label`/`label_to_id` 포맷도 동일하게 저장.
- 학습 중 `seqeval` 기반 개체 단위 P/R/F1을 valid셋으로 로깅.
- 학습 완료 후 3번의 실제질의 홀드아웃셋으로 최종 지표를 별도 산출.
- 산출물(체크포인트, `labels.json`, 토크나이저 파일)은 원격 학습 환경에서 이 저장소의 `backend/course_custom_ner_model/models/course-custom-ner/`로 수동 복사 — 기존 파일을 덮어쓰기 전에 현재 모델을 백업해두는 절차를 스크립트 사용법 문서에 명시.

### 5. 평가 계획

1. 학습 중 seqeval P/R/F1 (자동, `train.py`에 내장).
2. 학습 후 실제질의 홀드아웃셋 평가 (3번).
3. (선택, 여유 있으면) 새 모델로 교체한 뒤 이미 만들어둔 `backend/eval/run_eval.py` 골든셋 43개를 다시 돌려서, NER 개선이 파이프라인 전체 정확도(현재 27.9%)에 실제로 영향을 주는지 확인. 이 단계는 새 모델의 효과를 최종적으로 검증하는 것으로, 이번 재학습 작업의 성공 기준이자 이미 구축된 회귀 도구를 재사용하는 것이다.

## Out of scope

- 약어 **교정 로직**(`keyword_extract.py`의 `find_best_db_match`, sequential-match 최저점 문제 등) 수정 — 별도 작업.
- PROFESSOR 약어 유추.
- 모델 아키텍처 변경(더 큰 백본 등) — 이번엔 동일 구조 유지.
- RAG/few-shot 프롬프트 개선 — 별도 트랙.
- 라벨 스키마 자체의 재설계(16개 → 9개로 축소 등) — 이번엔 기존 스키마 유지, 데이터 배분만 조정.

## 알려진 리스크

- **자동 약어 유추의 정밀도**: 특히 COURSE_NAME은 카디널리티가 높아 자동 생성된 약어 후보의 상당수가 부정확할 수 있음 — 그래서 사람 검수 단계를 필수로 둠.
- **템플릿 다양성의 한계**: `backend-log.txt` 207개 문장도 결국 한정된 사용자층(테스트 인원)의 표현이라, 실제 서비스 사용자 전체의 다양성을 대표하지 못할 수 있음.
- **원격 학습 환경 재현성**: 이 머신이 아닌 별도 환경에서 학습하므로, Python/transformers/torch 버전 차이로 인한 재현성 문제 가능성 — `requirements.txt`에 학습 전용 의존성을 명시하는 것으로 완화.
