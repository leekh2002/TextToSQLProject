from backend.keyword_extract import build_corrected_query, correct_ner_entities


def ent(text, label, start):
    return {"text": text, "label": label, "start": start, "end": start + len(text), "score": 0.99}


def _correct(query, entities, references):
    corrected = correct_ner_entities(entities, references=references)
    return corrected, build_corrected_query(query, corrected)


def test_a_too_wide_span_keeps_the_words_the_match_does_not_cover():
    # The model tagged '데이터베이스 관련' as one COURSE_NAME. Replacing the whole
    # span with the matched DB value used to delete '관련', which was the only
    # signal that the user wanted a LIKE search.
    query = "데이터베이스 관련 과목 알려줘"
    references = {"COURSE_NAME": ["데이터베이스", "데이터베이스설계"]}

    corrected, corrected_query = _correct(query, [ent("데이터베이스 관련", "COURSE_NAME", 0)], references)

    assert corrected_query == query
    assert corrected[0]["corrected_text"] == "데이터베이스"


def test_a_match_covering_the_whole_span_still_replaces_it():
    query = "컴융 과목 보여줘"
    references = {"DEPARTMENT": ["컴퓨터융합학부"]}

    _, corrected_query = _correct(query, [ent("컴융", "DEPARTMENT", 0)], references)

    assert corrected_query == "컴퓨터융합학부 과목 보여줘"


def test_a_match_that_differs_only_in_spacing_is_not_applied():
    # '컴퓨터프로그래밍3' already identifies the course; rewriting it to the DB
    # spelling '컴퓨터프로그래밍 3' adds nothing and sent the LLM down a
    # different SQL path.
    query = "컴퓨터프로그래밍3 과목 선수과목이 뭐야"
    references = {"COURSE_NAME": ["컴퓨터프로그래밍 3"]}

    corrected, corrected_query = _correct(query, [ent("컴퓨터프로그래밍3", "COURSE_NAME", 0)], references)

    assert corrected_query == query
    assert corrected[0]["correction_applied"] is False


def test_a_match_that_differs_in_case_is_still_applied():
    query = "grade 방식 과목 알려줘"
    references = {"EVAL_TYPE": ["GRADE"]}

    _, corrected_query = _correct(query, [ent("grade", "EVAL_TYPE", 0)], references)

    assert corrected_query == "GRADE 방식 과목 알려줘"


def test_a_match_that_differs_in_punctuation_is_still_applied():
    query = "전공핵심 과목 보여줘"
    references = {"CATEGORY": ["전공(핵심)"]}

    _, corrected_query = _correct(query, [ent("전공핵심", "CATEGORY", 0)], references)

    assert corrected_query == "전공(핵심) 과목 보여줘"


def test_correction_still_works_on_entities_that_carry_no_offsets():
    # correct_ner_entities is also called with bare {text, label} dicts
    # (backend/test_correction.py), so offsets must stay optional.
    references = {"DEPARTMENT": ["컴퓨터융합학부"]}

    corrected = correct_ner_entities([{"text": "컴융부", "label": "DEPARTMENT"}], references=references)

    assert corrected[0]["corrected_text"] == "컴퓨터융합학부"
