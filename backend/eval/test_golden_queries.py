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


def test_golden_queries_file_has_43_cases():
    cases = _load_cases()
    assert len(cases) == 43


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


def test_category_counts_match_design():
    cases = _load_cases()
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {
        "course_filter": 15,
        "exclude_completed_courses": 5,
        "prerequisite": 5,
        "enrollment_aggregate": 5,
        "personalized_lookup": 5,
        "graduation_requirement": 3,
        "ambiguous_reject": 5,
    }
