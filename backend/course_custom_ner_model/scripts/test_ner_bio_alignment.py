from ner_bio_alignment import (
    char_spans_to_bio,
    compute_confusion_counts,
    format_confusion_report,
    ids_to_bio_labels,
)

LABEL_TO_ID = {"O": 0, "B-DEPARTMENT": 1, "I-DEPARTMENT": 2, "B-CATEGORY": 3, "I-CATEGORY": 4}
ID_TO_LABEL = {v: k for k, v in LABEL_TO_ID.items()}


def test_char_spans_to_bio_marks_special_tokens_as_ignored():
    entities = [{"start": 0, "end": 7, "label": "DEPARTMENT"}]
    offset_mapping = [(0, 0), (0, 3), (3, 7), (8, 10), (0, 0)]
    result = char_spans_to_bio(entities, offset_mapping, LABEL_TO_ID)
    assert result == [-100, 1, 2, 0, -100]


def test_char_spans_to_bio_handles_two_separate_entities():
    entities = [
        {"start": 0, "end": 3, "label": "DEPARTMENT"},
        {"start": 4, "end": 7, "label": "CATEGORY"},
    ]
    offset_mapping = [(0, 0), (0, 3), (4, 7), (0, 0)]
    result = char_spans_to_bio(entities, offset_mapping, LABEL_TO_ID)
    assert result == [-100, 1, 3, -100]


def test_char_spans_to_bio_returns_o_for_tokens_outside_any_entity():
    entities = []
    offset_mapping = [(0, 0), (0, 3), (0, 0)]
    result = char_spans_to_bio(entities, offset_mapping, LABEL_TO_ID)
    assert result == [-100, 0, -100]


def test_ids_to_bio_labels_skips_ignored_positions():
    ids = [-100, 1, 2, 0, -100]
    assert ids_to_bio_labels(ids, ID_TO_LABEL) == ["B-DEPARTMENT", "I-DEPARTMENT", "O"]


def test_compute_confusion_counts_strips_bio_prefix_and_counts_pairs():
    true_seqs = [["B-DEPARTMENT", "I-DEPARTMENT", "O"]]
    pred_seqs = [["B-CATEGORY", "I-DEPARTMENT", "O"]]
    counts = compute_confusion_counts(true_seqs, pred_seqs)
    assert counts[("DEPARTMENT", "CATEGORY")] == 1
    assert counts[("DEPARTMENT", "DEPARTMENT")] == 1
    assert counts[("O", "O")] == 1


def test_format_confusion_report_lists_every_pair_with_nonzero_count():
    counts = {("DEPARTMENT", "CATEGORY"): 2, ("DEPARTMENT", "DEPARTMENT"): 5}
    report = format_confusion_report(counts)
    assert "DEPARTMENT" in report
    assert "CATEGORY" in report
    assert "2" in report
    assert "5" in report
