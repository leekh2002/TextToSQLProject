from infer_abbreviations import (
    abbreviate_by_initials,
    generate_abbreviation_candidates,
    infer_abbreviations,
    mine_root_words,
    segment_by_roots,
    split_parenthetical,
    strip_department_prefix,
    strip_known_suffix,
)


def test_strip_department_prefix_removes_college_name():
    assert strip_department_prefix("공과대학 컴퓨터융합학부") == "컴퓨터융합학부"


def test_strip_department_prefix_leaves_value_without_prefix_unchanged():
    assert strip_department_prefix("컴퓨터융합학부") == "컴퓨터융합학부"


def test_strip_known_suffix_removes_longest_matching_suffix():
    assert strip_known_suffix("컴퓨터공학과", ["학과", "과"]) == "컴퓨터공"


def test_strip_known_suffix_leaves_value_unchanged_when_no_suffix_matches():
    assert strip_known_suffix("컴퓨터공학과", ["학부"]) == "컴퓨터공학과"


def test_mine_root_words_keeps_substrings_at_or_above_min_freq():
    values = ["컴퓨터공학과", "컴퓨터융합학부", "컴퓨터인공지능학부", "전자공학과", "기계공학부"]
    roots = mine_root_words(values, min_len=2, max_len=4, min_freq=3)
    assert "컴퓨터" in roots


def test_mine_root_words_excludes_rare_substrings():
    values = ["컴퓨터공학과", "컴퓨터융합학부", "컴퓨터인공지능학부", "전자공학과", "기계공학부"]
    roots = mine_root_words(values, min_len=2, max_len=4, min_freq=3)
    assert "인공지능" not in roots


def test_segment_by_roots_matches_longest_root_greedily():
    roots = ["컴퓨터", "컴", "공"]
    assert segment_by_roots("컴퓨터공", roots) == ["컴퓨터", "공"]


def test_segment_by_roots_falls_back_to_single_characters():
    assert segment_by_roots("공", ["컴퓨터"]) == ["공"]


def test_abbreviate_by_initials_takes_first_character_of_each_segment():
    assert abbreviate_by_initials(["컴퓨터", "공"]) == "컴공"


def test_abbreviate_by_initials_handles_empty_segment_list():
    assert abbreviate_by_initials([]) == ""


def test_split_parenthetical_extracts_both_groups():
    assert split_parenthetical("전공(핵심)") == ("전공", "핵심")


def test_split_parenthetical_returns_none_when_no_parentheses():
    assert split_parenthetical("일반선택") is None


def test_generate_abbreviation_candidates_for_department_matches_known_alias():
    roots = ["컴퓨터", "공학", "융합"]
    candidates = generate_abbreviation_candidates(
        "공과대학 컴퓨터공학과", "DEPARTMENT", roots, suffixes=["학과", "학부"]
    )
    assert "컴공" in candidates


def test_generate_abbreviation_candidates_for_category_uses_parenthetical_initials():
    candidates = generate_abbreviation_candidates("전공(핵심)", "CATEGORY", roots=[])
    assert "전핵" in candidates


def test_generate_abbreviation_candidates_for_category_without_parens_is_empty():
    candidates = generate_abbreviation_candidates("일반선택", "CATEGORY", roots=[])
    assert candidates == []


def test_generate_abbreviation_candidates_never_returns_value_itself():
    roots = ["데이터베이스"]
    candidates = generate_abbreviation_candidates("데이터베이스", "COURSE_NAME", roots)
    assert "데이터베이스" not in candidates


def test_infer_abbreviations_covers_every_requested_label():
    values_by_label = {
        "DEPARTMENT": ["공과대학 컴퓨터공학과", "공과대학 컴퓨터융합학부", "공과대학 컴퓨터인공지능학부"],
        "CATEGORY": ["전공(핵심)", "전공(기초)", "일반선택"],
    }
    suffixes_by_label = {"DEPARTMENT": ["학과", "학부"], "CATEGORY": []}
    result = infer_abbreviations(values_by_label, suffixes_by_label)
    assert set(result.keys()) == {"DEPARTMENT", "CATEGORY"}
    assert "전핵" in result["CATEGORY"]["전공(핵심)"]


def test_infer_abbreviations_skips_values_with_no_candidates():
    values_by_label = {"CATEGORY": ["일반선택"]}
    suffixes_by_label = {"CATEGORY": []}
    result = infer_abbreviations(values_by_label, suffixes_by_label)
    assert "일반선택" not in result["CATEGORY"]
