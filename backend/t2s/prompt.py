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
    return f"[값 후보 — 질문에 언급된 조건에만 정확한 값으로 쓰고, 질문에 없는 조건은 추가하지 마라]\n{lines}\n\n질문: {question}"


def build_messages(question, *, schema, hints, examples, logged_in, exclude_completed) -> list[dict]:
    messages = [{"role": "system", "content": _system_content(schema, logged_in, exclude_completed)}]
    for example in examples:
        messages.append({"role": "user", "content": f"질문: {example.question}"})
        messages.append({"role": "assistant", "content": example.sql})
    messages.append({"role": "user", "content": _user_content(question, hints)})
    return messages
