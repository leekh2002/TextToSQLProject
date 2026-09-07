import json

from train import load_jsonl, load_label_schema, tokenize_and_align


def test_load_jsonl_reads_one_record_per_line(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"text": "a", "entities": []}\n{"text": "b", "entities": []}\n',
        encoding="utf-8",
    )
    records = load_jsonl(str(path))
    assert records == [{"text": "a", "entities": []}, {"text": "b", "entities": []}]


def test_load_label_schema_reads_label_to_id_and_id_to_label(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps({"label_to_id": {"O": 0, "B-DEPARTMENT": 1}, "id_to_label": {"0": "O", "1": "B-DEPARTMENT"}}),
        encoding="utf-8",
    )
    label_to_id, id_to_label = load_label_schema(str(path))
    assert label_to_id == {"O": 0, "B-DEPARTMENT": 1}
    assert id_to_label == {0: "O", 1: "B-DEPARTMENT"}


def test_tokenize_and_align_produces_labels_aligned_to_tokens():
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("monologg/koelectra-small-v3-discriminator")
    label_to_id = {"O": 0, "B-DEPARTMENT": 1, "I-DEPARTMENT": 2}
    records = [{"text": "컴퓨터융합학부 과목", "entities": [{"start": 0, "end": 7, "label": "DEPARTMENT"}]}]

    dataset = tokenize_and_align(records, tokenizer, label_to_id, max_length=32)

    assert len(dataset) == 1
    example = dataset[0]
    assert "input_ids" in example
    assert "labels" in example
    assert 1 in example["labels"]
