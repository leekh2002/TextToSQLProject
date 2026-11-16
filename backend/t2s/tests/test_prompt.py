from backend.t2s.examples import Example
from backend.t2s.prompt import ANON_RULE, EXCLUDE_RULE, STUDENT_RULES, build_messages
from backend.t2s.values import ValueCandidate

EXCLUDE_USER_HINT = "(이미 들은 과목 제외는 시스템이 따로 처리한다. 그 부분은 무시하고 나머지 조건에 맞는 강의 목록 SQL을 작성한다.)"


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
    assert ANON_RULE in messages[0]["content"]
    assert not any(rule in messages[0]["content"] for rule in STUDENT_RULES)
    assert messages[1]["content"] == "질문: 질문1" and messages[2]["content"] == "SELECT 1"
    assert "dept_name = '공과대학 컴퓨터융합학부'" in messages[-1]["content"]
    assert messages[-1]["content"].endswith("질문: 컴융 목요일 과목")


def test_student_and_exclusion_rules():
    content = build_messages("q", schema="s", hints=[], examples=[], logged_in=True, exclude_completed=True)[0]["content"]

    assert all(rule in content for rule in STUDENT_RULES) and EXCLUDE_RULE in content
    assert ANON_RULE not in content


def test_student_rules_text():
    assert len(STUDENT_RULES) == 4
    assert STUDENT_RULES[0].startswith("로그인한 학생 본인 정보는 student AS s, enrollment AS e처럼 별칭을 쓰고")
    assert "dept_name = (SELECT d.dept_name FROM student AS s JOIN department AS d" in STUDENT_RULES[2]


def test_exclude_hint_appended_to_final_message_only_when_excluding():
    on = build_messages("q", schema="s", hints=[], examples=[], logged_in=True, exclude_completed=True)[-1]["content"]
    off = build_messages("q", schema="s", hints=[], examples=[], logged_in=True, exclude_completed=False)[-1]["content"]

    assert on == f"질문: q\n{EXCLUDE_USER_HINT}"
    assert off == "질문: q"


def test_exclude_hint_follows_hint_block():
    last = build_messages("q", schema="s", hints=[ValueCandidate("dept_name", "v", 90, "ngram")], examples=[],
                          logged_in=True, exclude_completed=True)[-1]["content"]

    assert last.startswith("[값 후보 — 참고용, 틀릴 수 있음]")
    assert last.endswith(f"질문: q\n{EXCLUDE_USER_HINT}")


def test_no_hint_block_when_no_hints():
    last = build_messages("q", schema="s", hints=[], examples=[], logged_in=False, exclude_completed=False)[-1]

    assert last["content"] == "질문: q"


def test_aggregate_and_abbreviation_rules_present():
    from backend.t2s.prompt import DOMAIN_RULES
    rules = "\n".join(DOMAIN_RULES)

    assert "'정원보다 많이 신청한', '정원 초과'는 enrolled > capacity이다. '정원이 다 찬', '마감'만 enrolled >= capacity AND capacity > 0이다." in rules
    assert "최다·최소·순위 질문은 정렬 기준 값도 SELECT에 넣는다(예: capacity - enrolled AS remaining_seats, COUNT(...) AS course_count)." in rules
    assert "단과대학 약칭은 정식 이름으로 바꿔 찾는다: 공대→공과대학, 자연대→자연과학대학, 경상대→경상대학, 사회대→사회과학대학, 인문대→인문대학." in rules


def test_hint_header_marks_candidates_as_reference():
    from backend.t2s.values import ValueCandidate as VC
    last = build_messages("q", schema="s", hints=[VC("dept_name", "v", 90, "ngram")], examples=[], logged_in=False,
                          exclude_completed=False)[-1]["content"]
    assert last.startswith("[값 후보 — 참고용, 틀릴 수 있음]")
