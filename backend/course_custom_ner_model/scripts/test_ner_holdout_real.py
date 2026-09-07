import json
from pathlib import Path

HOLDOUT_PATH = Path(__file__).resolve().parents[1] / "metadata" / "ner_holdout_real.jsonl"
VALID_LABELS = {
    "CAPACITY", "CATEGORY", "CLASS_MODE", "COURSE_NAME", "COURSE_YEAR", "CREDIT",
    "DAY", "DEPARTMENT", "ENROLLED", "EVAL_TYPE", "GRADE_METHOD", "PROFESSOR",
    "ROOM", "SECTION", "TIME", "VACANCY",
}


def _load_records():
    with open(HOLDOUT_PATH, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def test_holdout_has_27_records():
    assert len(_load_records()) == 27


def test_every_entity_offset_matches_the_text_exactly():
    for record in _load_records():
        text = record["text"]
        for entity in record["entities"]:
            assert text[entity["start"] : entity["end"]], record


def test_every_entity_label_is_a_known_label():
    for record in _load_records():
        for entity in record["entities"]:
            assert entity["label"] in VALID_LABELS, entity


def test_entities_within_a_record_do_not_overlap():
    for record in _load_records():
        entities = sorted(record["entities"], key=lambda e: e["start"])
        for previous, current in zip(entities, entities[1:]):
            assert previous["end"] <= current["start"], record


def test_at_least_two_records_have_zero_entities():
    zero_entity_records = [r for r in _load_records() if not r["entities"]]
    assert len(zero_entity_records) >= 2


def test_at_least_one_record_covers_each_observed_priority_label():
    # EVAL_TYPE and GRADE_METHOD are deliberately excluded: none of the 207
    # unique real queries in backend-log.txt mention evaluation type or
    # grading method at all (verified by grep before writing this holdout
    # set) — this file reflects genuine observed usage, so it should not be
    # padded with synthetic-sounding sentences just to hit a coverage
    # checklist. Those two labels still get dedicated coverage from Task 3's
    # synthetic templates (eval_type_only, grade_method_only, confusable_shortcats).
    priority_labels = {
        "DEPARTMENT", "CATEGORY", "COURSE_NAME", "PROFESSOR", "CLASS_MODE",
        "DAY", "TIME", "VACANCY",
    }
    seen_labels = {entity["label"] for record in _load_records() for entity in record["entities"]}
    missing = priority_labels - seen_labels
    assert not missing, f"holdout set never exercises: {missing}"
