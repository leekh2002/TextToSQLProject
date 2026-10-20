import json
from pathlib import Path

GOLDEN_QUERIES_PATH = Path(__file__).with_name("golden_queries.json")
VALID_GRADING_MODES = {"execution", "structural"}
REQUIRED_KEYS = {
    "id",
    "category",
    "query",
    "grading",
    "reference_sql",
    "order_sensitive",
    "expects_error",
    "student_id",
    "exclude_completed_courses",
    "structural_checks",
    "notes",
}


def _load_cases():
    with open(GOLDEN_QUERIES_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def test_all_case_ids_are_unique():
    cases = _load_cases()
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))


def test_every_case_has_required_keys():
    cases = _load_cases()
    for case in cases:
        missing = REQUIRED_KEYS - set(case.keys())
        assert not missing, f"{case.get('id')}: 누락된 키 {missing}"


def test_grading_mode_is_valid():
    cases = _load_cases()
    for case in cases:
        assert case["grading"] in VALID_GRADING_MODES, case["id"]


def test_execution_cases_have_reference_sql():
    cases = _load_cases()
    for case in cases:
        if case["grading"] == "execution":
            assert case["reference_sql"], f"{case['id']}: reference_sql이 비어있습니다"
            assert case["reference_sql"].strip().lower().startswith("select"), case["id"]


def test_structural_non_error_cases_have_checks():
    cases = _load_cases()
    for case in cases:
        if case["grading"] == "structural" and not case["expects_error"]:
            checks = case["structural_checks"]
            assert checks, f"{case['id']}: structural_checks가 비어있습니다"
            assert checks.get("required_tables"), f"{case['id']}: required_tables가 비어있습니다"


def test_optional_fields_have_valid_types():
    for case in _load_cases():
        if "empty_gold" in case:
            assert isinstance(case["empty_gold"], bool), case["id"]
        if "gold_values" in case:
            assert isinstance(case["gold_values"], list), case["id"]
            for item in case["gold_values"]:
                assert set(item) == {"column", "value"}, case["id"]


def test_category_counts_match_the_expanded_design():
    counts: dict[str, int] = {}
    for case in _load_cases():
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {
        "course_filter": 80,
        "prerequisite": 30,
        "enrollment_aggregate": 35,
        "personalized_lookup": 30,
        "exclude_completed_courses": 30,
        "ambiguous_reject": 30,
        "graduation_requirement": 3,
    }


def test_non_reject_cases_carry_gold_values():
    for case in _load_cases():
        if not case["expects_error"] and case["category"] != "graduation_requirement":
            assert "gold_values" in case, case["id"]
