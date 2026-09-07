from ner_template_engine import render_template


def test_render_template_substitutes_single_slot():
    result = render_template("{DEPARTMENT} 과목 보여줘", {"DEPARTMENT": ("컴퓨터융합학부", "DEPARTMENT")})
    assert result["text"] == "컴퓨터융합학부 과목 보여줘"
    assert result["entities"] == [{"start": 0, "end": 7, "label": "DEPARTMENT"}]


def test_render_template_computes_correct_offsets_for_multiple_slots():
    template = "{DEPARTMENT} {CATEGORY} 과목 알려줘"
    values = {
        "DEPARTMENT": ("컴퓨터융합학부", "DEPARTMENT"),
        "CATEGORY": ("전공(핵심)", "CATEGORY"),
    }
    result = render_template(template, values)
    assert result["text"] == "컴퓨터융합학부 전공(핵심) 과목 알려줘"
    assert result["entities"] == [
        {"start": 0, "end": 7, "label": "DEPARTMENT"},
        {"start": 8, "end": 14, "label": "CATEGORY"},
    ]


def test_render_template_supports_two_slots_of_the_same_label():
    template = "{COURSE_NAME}이랑 {COURSE_NAME_2} 보여줘"
    values = {
        "COURSE_NAME": ("데이터베이스", "COURSE_NAME"),
        "COURSE_NAME_2": ("자료구조", "COURSE_NAME"),
    }
    result = render_template(template, values)
    assert result["text"] == "데이터베이스이랑 자료구조 보여줘"
    assert result["entities"] == [
        {"start": 0, "end": 6, "label": "COURSE_NAME"},
        {"start": 9, "end": 13, "label": "COURSE_NAME"},
    ]


def test_render_template_with_no_placeholders_returns_no_entities():
    result = render_template("오늘 날씨 어때?", {})
    assert result == {"text": "오늘 날씨 어때?", "entities": []}


def test_render_template_entities_are_sorted_by_start():
    template = "{B} 그리고 {A}"
    values = {"A": ("가", "CATEGORY"), "B": ("나", "DEPARTMENT")}
    result = render_template(template, values)
    starts = [entity["start"] for entity in result["entities"]]
    assert starts == sorted(starts)


def test_render_template_raises_on_missing_value_for_placeholder():
    try:
        render_template("{DEPARTMENT} 보여줘", {})
        assert False, "expected KeyError"
    except KeyError:
        pass
