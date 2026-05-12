import argparse
import json
import os
from collections import OrderedDict

import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification


def slot_key(label: str) -> str:
    return label.lower()


class CourseNERPredictor:
    def __init__(self, model_dir: str, max_length: int = 128):
        self.model_dir = model_dir
        self.max_length = max_length
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForTokenClassification.from_pretrained(model_dir).to(self.device)
        self.model.eval()

        label_path = os.path.join(model_dir, "labels.json")

        with open(label_path, "r", encoding="utf-8") as f:
            label_data = json.load(f)

        self.id_to_label = {
            int(key): value
            for key, value in label_data["id_to_label"].items()
        }
        self.entity_types = label_data["entity_types"]

    @torch.no_grad()
    def extract(self, text: str):
        encoded = self.tokenizer(
            text,
            return_tensors="pt",
            return_offsets_mapping=True,
            truncation=True,
            max_length=self.max_length,
        )

        offsets = encoded.pop("offset_mapping")[0].tolist()
        encoded = {
            key: value.to(self.device)
            for key, value in encoded.items()
        }

        outputs = self.model(**encoded)
        probs = torch.softmax(outputs.logits[0], dim=-1)

        pred_ids = torch.argmax(probs, dim=-1).tolist()
        pred_scores = torch.max(probs, dim=-1).values.tolist()

        token_predictions = []

        for pred_id, score, (start, end) in zip(pred_ids, pred_scores, offsets):
            if start == end:
                continue

            label = self.id_to_label[pred_id]

            token_predictions.append({
                "start": start,
                "end": end,
                "label": label,
                "score": float(score),
            })

        return self._merge_bio(text, token_predictions)

    def _merge_bio(self, text, token_predictions):
        entities = []
        current = None

        for token in token_predictions:
            label = token["label"]

            if label == "O":
                if current:
                    entities.append(current)
                    current = None
                continue

            if "-" not in label:
                continue

            prefix, entity_type = label.split("-", 1)

            if prefix == "B" or current is None or current["label"] != entity_type:
                if current:
                    entities.append(current)

                current = {
                    "label": entity_type,
                    "start": token["start"],
                    "end": token["end"],
                    "scores": [token["score"]],
                }
            else:
                current["end"] = token["end"]
                current["scores"].append(token["score"])

        if current:
            entities.append(current)

        result = []

        for entity in entities:
            start = entity["start"]
            end = entity["end"]
            score = sum(entity["scores"]) / len(entity["scores"])

            result.append({
                "text": text[start:end],
                "label": entity["label"],
                "start": start,
                "end": end,
                "score": round(score, 4),
            })

        return result


def build_slots(entities):
    slots = OrderedDict()

    for entity in entities:
        key = slot_key(entity["label"])

        if key not in slots:
            slots[key] = []

        value = entity["text"]

        if value not in slots[key]:
            slots[key].append(value)

    return dict(slots)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--model_dir", default="models/course-custom-ner")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max_length", type=int, default=128)

    args = parser.parse_args()

    predictor = CourseNERPredictor(
        model_dir=args.model_dir,
        max_length=args.max_length,
    )

    entities = predictor.extract(args.query)

    result = {
        "query": args.query,
        "entities": entities,
        "slots": build_slots(entities),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()