from backend.keyword_extract import postprocess_entities


def ent(text, label, start, score=0.9):
    return {"text": text, "label": label, "start": start, "end": start + len(text), "score": score}


def test_trailing_particle_is_trimmed_from_a_department_span():
    text = "공과대학 컴퓨터융합학부에 개설된 과목"
    entities = [ent("공과대학 컴퓨터융합학부에", "DEPARTMENT", 0)]

    result = postprocess_entities(entities, text)

    assert [e["text"] for e in result] == ["공과대학 컴퓨터융합학부"]


def test_longer_particle_is_trimmed_before_its_shorter_prefix():
    text = "응화공에서 개설한 과목 보여줘"
    entities = [ent("응화공에서", "DEPARTMENT", 0)]

    result = postprocess_entities(entities, text)

    assert [e["text"] for e in result] == ["응화공"]


def test_department_name_ending_in_gwa_is_left_alone():
    text = "공과대학 응용화학공학과 전공"
    entities = [ent("공과대학 응용화학공학과", "DEPARTMENT", 0)]

    result = postprocess_entities(entities, text)

    assert [e["text"] for e in result] == ["공과대학 응용화학공학과"]


def test_vacancy_phrase_ending_in_neun_is_left_alone():
    text = "빈자리가 있는 과목 알려줘"
    entities = [ent("빈자리가 있는", "VACANCY", 0)]

    result = postprocess_entities(entities, text)

    assert [e["text"] for e in result] == ["빈자리가 있는"]


def test_trailing_punctuation_is_trimmed():
    text = "1시 ~ 3시 사이 강의"
    entities = [ent("1시 ~", "TIME", 0)]

    result = postprocess_entities(entities, text)

    assert [e["text"] for e in result] == ["1시"]


def test_single_character_fragment_is_dropped():
    text = "2학년대상 전공과목 찾아줘"
    entities = [ent("과", "DEPARTMENT", 7)]

    result = postprocess_entities(entities, text)

    assert result == []


def test_single_character_weekday_is_kept_for_the_day_label():
    text = "금 3시 강의"
    entities = [ent("금", "DAY", 0)]

    result = postprocess_entities(entities, text)

    assert [e["text"] for e in result] == ["금"]


def test_span_consisting_only_of_a_particle_is_dropped():
    text = "컴퓨터융합학부에서 개설한 과목"
    entities = [ent("에서", "COURSE_NAME", 7)]

    result = postprocess_entities(entities, text)

    assert result == []


def test_offsets_stay_consistent_with_the_trimmed_text():
    text = "공과대학 컴퓨터융합학부에서 개설한 과목"
    entities = [ent("공과대학 컴퓨터융합학부에서", "DEPARTMENT", 0)]

    result = postprocess_entities(entities, text)

    entity = result[0]
    assert text[entity["start"] : entity["end"]] == entity["text"]


def test_a_word_whose_last_syllable_looks_like_a_particle_is_not_cut():
    # '사이' ends in 이, but 이 here is part of the word, not a particle.
    # Single-character particles cannot be told apart from word endings
    # without morphological analysis, so they must not be trimmed.
    text = "1시 ~ 3시 사이 강의"
    entities = [ent("3시 사이", "TIME", 5)]

    result = postprocess_entities(entities, text)

    assert [e["text"] for e in result] == ["3시 사이"]


def test_a_clean_entity_passes_through_untouched():
    text = "전공(핵심) 과목 보여줘"
    entities = [ent("전공(핵심)", "CATEGORY", 0)]

    result = postprocess_entities(entities, text)

    assert result == entities
