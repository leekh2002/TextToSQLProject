from __future__ import annotations

import argparse
import json
from pathlib import Path

from ner_bio_alignment import (
    char_spans_to_bio,
    compute_confusion_counts,
    format_confusion_report,
    ids_to_bio_labels,
)


def load_jsonl(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def load_label_schema(labels_json_path: str) -> tuple[dict[str, int], dict[int, str]]:
    with open(labels_json_path, "r", encoding="utf-8") as file:
        data = json.load(file)
    label_to_id = {label: int(value) for label, value in data["label_to_id"].items()}
    id_to_label = {int(key): value for key, value in data["id_to_label"].items()}
    return label_to_id, id_to_label


def tokenize_and_align(records: list[dict], tokenizer, label_to_id: dict[str, int], max_length: int):
    from datasets import Dataset

    input_ids_list = []
    attention_mask_list = []
    labels_list = []

    for record in records:
        encoded = tokenizer(
            record["text"],
            truncation=True,
            max_length=max_length,
            return_offsets_mapping=True,
        )
        offset_mapping = encoded.pop("offset_mapping")
        labels = char_spans_to_bio(record["entities"], offset_mapping, label_to_id)

        input_ids_list.append(encoded["input_ids"])
        attention_mask_list.append(encoded["attention_mask"])
        labels_list.append(labels)

    return Dataset.from_dict(
        {
            "input_ids": input_ids_list,
            "attention_mask": attention_mask_list,
            "labels": labels_list,
        }
    )


def _evaluate_on_holdout(model, tokenizer, holdout_records: list[dict], label_to_id: dict[str, int], id_to_label: dict[int, str], max_length: int) -> None:
    import torch

    model.eval()
    true_seqs: list[list[str]] = []
    pred_seqs: list[list[str]] = []

    with torch.no_grad():
        for record in holdout_records:
            encoded = tokenizer(
                record["text"],
                truncation=True,
                max_length=max_length,
                return_offsets_mapping=True,
                return_tensors="pt",
            )
            offset_mapping = encoded.pop("offset_mapping")[0].tolist()
            true_ids = char_spans_to_bio(record["entities"], offset_mapping, label_to_id)

            outputs = model(**encoded)
            pred_ids = outputs.logits.argmax(dim=-1)[0].tolist()
            pred_ids_masked = [pred if true != -100 else -100 for pred, true in zip(pred_ids, true_ids)]

            true_seqs.append(ids_to_bio_labels(true_ids, id_to_label))
            pred_seqs.append(ids_to_bio_labels(pred_ids_masked, id_to_label))

    from seqeval.metrics import classification_report

    print("=== Holdout (real queries) seqeval report ===")
    print(classification_report(true_seqs, pred_seqs))
    print("=== Holdout (real queries) confusion counts ===")
    print(format_confusion_report(compute_confusion_counts(true_seqs, pred_seqs)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune course-custom-ner from a public KoELECTRA checkpoint")
    parser.add_argument("--base-checkpoint", default="monologg/koelectra-small-v3-discriminator")
    parser.add_argument("--train-file", default="../data/ner_train.jsonl")
    parser.add_argument("--valid-file", default="../data/ner_valid.jsonl")
    parser.add_argument("--holdout-file", default="../metadata/ner_holdout_real.jsonl")
    parser.add_argument("--labels-file", default="../models/course-custom-ner/labels.json")
    parser.add_argument("--output-dir", default="../trained_model_output")
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--num-train-epochs", type=float, default=8.0)
    parser.add_argument("--per-device-train-batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    args = parser.parse_args()

    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        DataCollatorForTokenClassification,
        Trainer,
        TrainingArguments,
    )

    label_to_id, id_to_label = load_label_schema(args.labels_file)

    tokenizer = AutoTokenizer.from_pretrained(args.base_checkpoint)
    model = AutoModelForTokenClassification.from_pretrained(
        args.base_checkpoint,
        num_labels=len(label_to_id),
        id2label=id_to_label,
        label2id=label_to_id,
    )

    train_records = load_jsonl(args.train_file)
    valid_records = load_jsonl(args.valid_file)
    holdout_records = load_jsonl(args.holdout_file)

    train_dataset = tokenize_and_align(train_records, tokenizer, label_to_id, args.max_length)
    valid_dataset = tokenize_and_align(valid_records, tokenizer, label_to_id, args.max_length)

    from ner_bio_alignment import build_compute_metrics

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.per_device_train_batch_size,
        learning_rate=args.learning_rate,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        logging_steps=20,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=valid_dataset,
        data_collator=DataCollatorForTokenClassification(tokenizer=tokenizer),
        compute_metrics=build_compute_metrics(id_to_label),
    )

    trainer.train()

    print("=== Final validation metrics ===")
    print(trainer.evaluate())

    _evaluate_on_holdout(model, tokenizer, holdout_records, label_to_id, id_to_label, args.max_length)

    final_dir = Path(args.output_dir) / "final"
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    with open(Path(args.labels_file), "r", encoding="utf-8") as file:
        labels_content = file.read()
    with open(final_dir / "labels.json", "w", encoding="utf-8") as file:
        file.write(labels_content)
    print(f"saved final model to {final_dir}")


if __name__ == "__main__":
    main()
