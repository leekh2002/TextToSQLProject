import json

import pytest

from eval_checkpoint import (
    collect_label_sequences,
    format_evaluation_report,
    resolve_labels_path,
)

LABEL_TO_ID = {"O": 0, "B-DEPARTMENT": 1, "I-DEPARTMENT": 2, "B-CATEGORY": 3, "I-CATEGORY": 4}
ID_TO_LABEL = {v: k for k, v in LABEL_TO_ID.items()}


def _write_labels_json(directory):
    path = directory / "labels.json"
    path.write_text(
        json.dumps({"label_to_id": LABEL_TO_ID, "id_to_label": {str(k): v for k, v in ID_TO_LABEL.items()}}),
        encoding="utf-8",
    )
    return path


def test_resolve_labels_path_defaults_to_labels_json_inside_the_model_dir(tmp_path):
    model_dir = tmp_path / "checkpoint"
    model_dir.mkdir()
    expected = _write_labels_json(model_dir)

    assert resolve_labels_path(str(model_dir)) == str(expected)


def test_resolve_labels_path_prefers_an_explicit_override(tmp_path):
    model_dir = tmp_path / "checkpoint"
    model_dir.mkdir()
    _write_labels_json(model_dir)
    override_dir = tmp_path / "elsewhere"
    override_dir.mkdir()
    override = _write_labels_json(override_dir)

    assert resolve_labels_path(str(model_dir), str(override)) == str(override)


def test_resolve_labels_path_exits_when_the_model_dir_has_no_labels_json(tmp_path):
    model_dir = tmp_path / "checkpoint"
    model_dir.mkdir()

    with pytest.raises(SystemExit):
        resolve_labels_path(str(model_dir))


def test_collect_label_sequences_derives_gold_labels_from_char_spans():
    records = [{"text": "컴퓨터융합학부", "entities": [{"start": 0, "end": 7, "label": "DEPARTMENT"}]}]

    def perfect_predict(text):
        return [(0, 0), (0, 3), (3, 7), (0, 0)], [0, 1, 2, 0]

    true_seqs, pred_seqs = collect_label_sequences(records, perfect_predict, LABEL_TO_ID, ID_TO_LABEL)

    assert true_seqs == [["B-DEPARTMENT", "I-DEPARTMENT"]]
    assert pred_seqs == [["B-DEPARTMENT", "I-DEPARTMENT"]]


def test_collect_label_sequences_drops_predictions_at_ignored_positions():
    records = [{"text": "과목", "entities": []}]

    def noisy_predict(text):
        return [(0, 0), (0, 2), (0, 0)], [1, 0, 3]

    true_seqs, pred_seqs = collect_label_sequences(records, noisy_predict, LABEL_TO_ID, ID_TO_LABEL)

    assert true_seqs == [["O"]]
    assert pred_seqs == [["O"]]


def test_collect_label_sequences_keeps_a_mislabeled_prediction():
    records = [{"text": "컴퓨터융합학부", "entities": [{"start": 0, "end": 7, "label": "DEPARTMENT"}]}]

    def confusing_predict(text):
        return [(0, 0), (0, 3), (3, 7), (0, 0)], [0, 3, 4, 0]

    true_seqs, pred_seqs = collect_label_sequences(records, confusing_predict, LABEL_TO_ID, ID_TO_LABEL)

    assert true_seqs == [["B-DEPARTMENT", "I-DEPARTMENT"]]
    assert pred_seqs == [["B-CATEGORY", "I-CATEGORY"]]


def test_format_evaluation_report_contains_a_seqeval_and_a_confusion_section():
    true_seqs = [["B-DEPARTMENT", "I-DEPARTMENT"]]
    pred_seqs = [["B-CATEGORY", "I-CATEGORY"]]

    report = format_evaluation_report("Holdout", true_seqs, pred_seqs)

    assert "Holdout" in report
    assert "seqeval report" in report
    assert "confusion counts" in report
    assert "DEPARTMENT -> CATEGORY" in report
