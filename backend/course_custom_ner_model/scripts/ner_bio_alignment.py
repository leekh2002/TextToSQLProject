from __future__ import annotations

from collections import Counter


def char_spans_to_bio(
    entities: list[dict],
    offset_mapping: list[tuple[int, int]],
    label_to_id: dict[str, int],
) -> list[int]:
    sorted_entities = sorted(entities, key=lambda e: e["start"])
    result: list[int] = []

    for start, end in offset_mapping:
        if start == end:
            result.append(-100)
            continue

        matched_entity = None
        for entity in sorted_entities:
            if entity["start"] <= start < entity["end"]:
                matched_entity = entity
                break

        if matched_entity is None:
            result.append(label_to_id["O"])
            continue

        prefix = "B" if start == matched_entity["start"] else "I"
        label_key = f"{prefix}-{matched_entity['label']}"
        result.append(label_to_id[label_key])

    return result


def ids_to_bio_labels(ids: list[int], id_to_label: dict[int, str]) -> list[str]:
    return [id_to_label[i] for i in ids if i != -100]


def _entity_type(bio_label: str) -> str:
    if bio_label == "O":
        return "O"
    return bio_label.split("-", 1)[1]


def compute_confusion_counts(
    true_label_seqs: list[list[str]],
    pred_label_seqs: list[list[str]],
) -> dict[tuple[str, str], int]:
    counts: Counter[tuple[str, str]] = Counter()
    for true_seq, pred_seq in zip(true_label_seqs, pred_label_seqs):
        for true_label, pred_label in zip(true_seq, pred_seq):
            counts[(_entity_type(true_label), _entity_type(pred_label))] += 1
    return dict(counts)


def format_confusion_report(counts: dict[tuple[str, str], int]) -> str:
    lines = ["true_label -> predicted_label : count"]
    for (true_label, pred_label), count in sorted(counts.items(), key=lambda item: -item[1]):
        lines.append(f"{true_label} -> {pred_label} : {count}")
    return "\n".join(lines)


def build_compute_metrics(id_to_label: dict[int, str]):
    import numpy as np
    from seqeval.metrics import f1_score, precision_score, recall_score

    def compute_metrics(eval_pred) -> dict[str, float]:
        predictions, labels = eval_pred
        predictions = np.argmax(predictions, axis=2)

        true_labels = [ids_to_bio_labels(label_row.tolist(), id_to_label) for label_row in labels]
        pred_labels = [
            ids_to_bio_labels(
                [pred if true != -100 else -100 for pred, true in zip(pred_row.tolist(), label_row.tolist())],
                id_to_label,
            )
            for pred_row, label_row in zip(predictions, labels)
        ]

        return {
            "precision": precision_score(true_labels, pred_labels),
            "recall": recall_score(true_labels, pred_labels),
            "f1": f1_score(true_labels, pred_labels),
        }

    return compute_metrics
