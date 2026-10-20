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


def test_short_value_inside_longer_matching_value_is_dropped():
    refs = {"class_mode": ["대면", "비대면"]}

    assert [c.value for c in from_ngrams("비대면 수업", refs)] == ["비대면"]
    assert [c.value for c in from_ngrams("대면 수업", refs)] == ["대면"]
    assert from_ngrams("가 수업", {"x": ["가"]}) == []
