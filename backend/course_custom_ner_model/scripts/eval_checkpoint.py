"""Score an already-trained NER checkpoint on labeled jsonl files.

Unlike `train.py`, this runs no training — it exists so the currently deployed
model and a freshly trained candidate can be measured on the same holdout set
before deciding whether to swap them.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ner_bio_alignment import (
    char_spans_to_bio,
    compute_confusion_counts,
    format_confusion_report,
    ids_to_bio_labels,
)
from train import load_jsonl, load_label_schema

DEFAULT_DATA_FILES = ["../metadata/ner_holdout_real.jsonl"]


def resolve_labels_path(model_dir: str, labels_file: str | None = None) -> str:
    if labels_file:
        return labels_file

    candidate = Path(model_dir) / "labels.json"
    if not candidate.is_file():
        raise SystemExit(
            f"No labels.json found in '{model_dir}' — pass --labels-file to point at one explicitly."
        )
    return str(candidate)


def collect_label_sequences(
    records: list[dict],
    predict,
    label_to_id: dict[str, int],
    id_to_label: dict[int, str],
) -> tuple[list[list[str]], list[list[str]]]:
    true_label_seqs: list[list[str]] = []
    pred_label_seqs: list[list[str]] = []

    for record in records:
        offset_mapping, pred_ids = predict(record["text"])
        true_ids = char_spans_to_bio(record["entities"], offset_mapping, label_to_id)
        masked_pred_ids = [pred if true != -100 else -100 for pred, true in zip(pred_ids, true_ids)]

        true_label_seqs.append(ids_to_bio_labels(true_ids, id_to_label))
        pred_label_seqs.append(ids_to_bio_labels(masked_pred_ids, id_to_label))

    return true_label_seqs, pred_label_seqs


def format_evaluation_report(
    name: str,
    true_label_seqs: list[list[str]],
    pred_label_seqs: list[list[str]],
) -> str:
    from seqeval.metrics import classification_report

    return "\n".join(
        [
            f"=== {name} seqeval report ===",
            classification_report(true_label_seqs, pred_label_seqs, zero_division=0),
            f"=== {name} confusion counts ===",
            format_confusion_report(compute_confusion_counts(true_label_seqs, pred_label_seqs)),
        ]
    )


def build_model_predictor(model_dir: str, max_length: int):
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForTokenClassification.from_pretrained(model_dir)
    model.eval()

    def predict(text: str) -> tuple[list[tuple[int, int]], list[int]]:
        with torch.no_grad():
            encoded = tokenizer(
                text,
                truncation=True,
                max_length=max_length,
                return_offsets_mapping=True,
                return_tensors="pt",
            )
            offset_mapping = encoded.pop("offset_mapping")[0].tolist()
            encoded = {key: value.to(model.device) for key, value in encoded.items()}
            logits = model(**encoded).logits
            return offset_mapping, logits.argmax(dim=-1)[0].tolist()

    return predict


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a trained course-custom-ner checkpoint without retraining")
    parser.add_argument("--model-dir", required=True, help="directory holding config.json + model weights")
    parser.add_argument(
        "--data-file",
        action="append",
        default=None,
        help=f"labeled jsonl to score on; repeatable (default: {DEFAULT_DATA_FILES[0]})",
    )
    parser.add_argument("--labels-file", default=None, help="defaults to <model-dir>/labels.json")
    parser.add_argument("--max-length", type=int, default=128)
    args = parser.parse_args()

    data_files = args.data_file or DEFAULT_DATA_FILES

    label_to_id, id_to_label = load_label_schema(resolve_labels_path(args.model_dir, args.labels_file))
    predict = build_model_predictor(args.model_dir, args.max_length)

    print(f"model: {args.model_dir}")

    for data_file in data_files:
        records = load_jsonl(data_file)
        if not records:
            raise SystemExit(f"No records loaded from '{data_file}' — check the path and content.")

        true_label_seqs, pred_label_seqs = collect_label_sequences(records, predict, label_to_id, id_to_label)
        print(format_evaluation_report(f"{Path(data_file).stem} ({len(records)} records)", true_label_seqs, pred_label_seqs))


if __name__ == "__main__":
    main()
