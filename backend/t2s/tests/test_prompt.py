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


def test_hint_header_marks_candidates_as_reference():
    from backend.t2s.values import ValueCandidate as VC
    last = build_messages("q", schema="s", hints=[VC("dept_name", "v", 90, "ngram")], examples=[], logged_in=False,
                          exclude_completed=False)[-1]["content"]
    assert last.startswith("[값 후보 — 참고용, 틀릴 수 있음]")
