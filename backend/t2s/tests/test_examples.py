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


def test_contamination_normalizes_student_placeholder_sql():
    golden = [{"id": "g1", "query": "선수과목 알려줘", "reference_sql": "SELECT a  FROM enrollment WHERE student_id = '202102671'"}]
    example = Example("e9", "컴융 금요일 과목", "select a from enrollment where student_id = %(student_id)s")

    problems = contamination([example], golden, embed)

    assert any("e9" in p and "정답 SQL 동일" in p for p in problems)


def test_contamination_flags_same_skeleton_with_similar_question():
    golden = [{"id": "g1", "query": "컴융 금요일 과목", "reference_sql": "SELECT * FROM v_course_info WHERE day_of_week = '금'"}]
    # similarity 0.99 is under the 0.995 threshold below, so only the template rule can flag it
    flagged = contamination([EXAMPLES[0]], golden, embed, threshold=0.995)
    assert any("e1" in p and "SQL 골격 동일" in p for p in flagged)
    # same skeleton but dissimilar question is fine; similar question with different skeleton is fine
    assert contamination([EXAMPLES[2]], golden, embed, threshold=0.995) == []
    other = [{"id": "g1", "query": "컴융 금요일 과목", "reference_sql": "SELECT COUNT(*) FROM v_course_info"}]
    assert contamination([EXAMPLES[0]], other, embed, threshold=0.995) == []


def test_is_personal_example():
    from backend.t2s.examples import Example, is_personal_example

    assert is_personal_example(Example("a", "q", "SELECT * FROM v_course_info WHERE x = %(student_id)s"))
    assert is_personal_example(Example("a", "q", "select * from Enrollment e"))
    assert is_personal_example(Example("a", "q", "SELECT * FROM student"))
    assert not is_personal_example(Example("a", "q", "SELECT * FROM v_course_info WHERE subject_name LIKE '%students%'"))
    assert not is_personal_example(Example("a", "q", "SELECT * FROM v_course_info"))
