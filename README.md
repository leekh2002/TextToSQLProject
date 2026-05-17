# Course Frontend (+ FastAPI backend)

**Vite(React) 프론트엔드**와 `backend/`의 **FastAPI(text-to-sql) 백엔드**

## 실행 방법 (개발)

- Anaconda 등의 가상환경 이용하여 실행 권장

### 프론트 + 백엔드 같이 실행

- NodeJS 설정 (Node.js 설치 필요 -> https://nodejs.org/ko/download/)

```bash
npm install
pip install -r backend/requirements.txt
npm run dev:full
```

- 프론트: `http://localhost:5173`
- 백엔드: `http://127.0.0.1:8000`
- 백엔드 헬스체크: `GET /api/v1/health`

### 환경변수

- 프론트: `.env` (예시는 `.env.example`)
  - `VITE_API_BASE_URL=/api/v1` 권장 (Vite proxy로 백엔드로 전달)
- 백엔드: `backend/.env` (예시는 `backend/.env.example`)
  - `OLLAMA_BASE_URL` (기본 `http://127.0.0.1:11434`)
  - `OLLAMA_MODEL` (예: `text2sql-local`)
  - `DATABASE_URL` (예: `postgresql://postgres:1234@localhost:5432/univ`)
  - `REDIS_URL` (선택)

> `DATABASE_URL`이 없으면 `/api/v1/query`는 에러 DB 부재 에러 반환, SQL 쿼리만 반환함

### 로컬 모델(Ollama) 준비

```bash 
ollama create text2sql-local -f "C:\충남대\4-1\종합설계\작업\모델\Modelfile"
ollama run text2sql-local
```

- `Modelfile`의 `FROM` 경로는 실제 `gguf` 경로로 수정
- API(OpenAI) 기반 백업 코드는 `backend/backup_api/`에 위치
- Run상태를 유지할 필요는 없지만, Ollama는 실행되어 있는 상태여야 함

## DB 설정

- 현재 설정은 PostgreSQL을 사용한다는 전제 하에 설정되어 있음. 다른 DB를 사용한다면 `backend/db.py` 파일의 코드 일부를 수정
- `backend/db.py`에서 DATABASE_URL은 본인 환경에 맞게 수정. 예: `postgresql://postgres:[PASSWORD]@localhost:[포트]/[DB명]`
- 추가적으로, 현재는 v_courses_info라는 view를 사용하도록 LLM이 설정되어 있기 때문에, DB 내에서 아래 SQL문을 실행하여 View를 설정해야 함.

```sql

CREATE OR REPLACE VIEW v_course_info AS
SELECT
    c.course_year,
    c.subject_code,
    c.section,
    s.subject_name,
    s.category,
    s.credit_hours,
    s.target_year,
    c.professor,
    c.capacity,
    c.enrolled,
    c.grading_method,
    c.eval_type,
    c.class_mode,
    d.dept_name,
    sch.day_of_week,
    sch.start_time,
    sch.end_time,
    sch.classroom
FROM cnu_courses c
JOIN subject s ON c.subject_code = s.subject_code
JOIN department d ON c.dept_code = d.dept_code
LEFT JOIN course_schedule sch ON c.subject_code = sch.subject_code AND c.section = sch.section;

```
## 사용한 모델

- Qwen2.5-Coder-7B (Instruct) 사용
- Ollama 3.1 8B 또한 사용 가능

- [모델 링크 (프로젝트 내 models 폴더에 위치)](https://drive.google.com/file/d/1t5IoSzCTg89vYgrI0YydIqNC4pOj_aVB/view?usp=sharing)
## Docker

Development containers are included for:

- `frontend`: Vite dev server
- `backend`: FastAPI app
- `postgres`: local PostgreSQL
- `redis`: local Redis

Run:

```bash
docker compose up --build
```

Endpoints:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Health: `http://localhost:8000/api/v1/health`

Notes:

- The frontend container proxies `/api/v1` to the backend service by using `VITE_BACKEND_TARGET=http://backend:8000`.
- The backend container is configured to connect to host Ollama with `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- PostgreSQL and Redis are started by Compose with container-local addresses.
- Your schema and seed data are not created automatically. The backend still expects tables such as `course_offerings`, `subject`, and `department`.
- The first backend image build can take time because it installs `torch` and `transformers`.

If you want Ollama inside Docker as well, add a separate Ollama service later with GPU/runtime and model volume settings.
