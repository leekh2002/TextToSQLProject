"""Verified question→SQL examples for few-shot prompting (spec 3.3), kept apart from the golden set."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

EXAMPLES_PATH = Path(__file__).with_name("data") / "examples.json"
REVIEW_LOG_PATH = Path(__file__).with_name("logs") / "review_queue.jsonl"
CONTAMINATION_THRESHOLD = 0.9


@dataclass(frozen=True)
class Example:
    id: str
    question: str
    sql: str


def load_examples(path: Path = EXAMPLES_PATH) -> list[Example]:
    with open(path, encoding="utf-8") as fh:
        return [Example(**item) for item in json.load(fh)]


def save_examples(examples: list[Example], path: Path = EXAMPLES_PATH) -> None:
    Path(path).write_text(
        json.dumps([asdict(e) for e in examples], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


PERSONAL_SQL = re.compile(r"%\(student_id\)s|\b(?:student|enrollment)\b", re.IGNORECASE)


def is_personal_example(example: Example) -> bool:
    return bool(PERSONAL_SQL.search(example.sql))


def sql_skeleton(sql: str) -> str:
    text = re.sub(r"'(?:[^']|'')*'", "'?'", sql)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "0", text)
    return re.sub(r"\s+", " ", text).strip().lower()


class ExampleStore:
    def __init__(self, examples: list[Example], embed):
        self.examples = list(examples)
        self._embed = embed
        self._matrix = np.vstack([embed(e.question) for e in self.examples]) if self.examples else None

    def search(self, question: str, k: int) -> list[tuple[Example, float]]:
        if self._matrix is None or k <= 0:
            return []
        scores = self._matrix @ self._embed(question)
        picked, skeletons = [], set()
        for index in np.argsort(-scores):
            example = self.examples[int(index)]
            skeleton = sql_skeleton(example.sql)
            if skeleton in skeletons:
                continue
            skeletons.add(skeleton)
            picked.append((example, float(scores[int(index)])))
            if len(picked) == k:
                break
        return picked


def embed_question(text: str) -> np.ndarray:
    from ..vector_cache import embed_text

    return np.frombuffer(embed_text(text), dtype=np.float32)


def contamination(examples, golden_cases, embed, threshold: float = CONTAMINATION_THRESHOLD) -> list[str]:
    problems = []
    golden_sql = {(c.get("reference_sql") or "").strip(): c["id"] for c in golden_cases if c.get("reference_sql")}
    golden_vectors = [(c["id"], embed(c["query"])) for c in golden_cases]
    for example in examples:
        if example.sql.strip() in golden_sql:
            problems.append(f"{example.id}: 평가셋 {golden_sql[example.sql.strip()]}와 정답 SQL 동일")
        vector = embed(example.question)
        for case_id, golden_vector in golden_vectors:
            similarity = float(vector @ golden_vector)
            if similarity >= threshold:
                problems.append(f"{example.id}: 평가셋 {case_id}와 질의 유사도 {similarity:.3f}")
    return problems


@lru_cache(maxsize=1)
def default_store() -> ExampleStore:
    return ExampleStore(load_examples(), embed_question)


def main(argv=None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="검증된 예시 저장소")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    approve = sub.add_parser("approve")
    approve.add_argument("--log-line", type=int, required=True)
    approve.add_argument("--id", required=True)
    args = parser.parse_args(argv)

    from ..eval.run_eval import GOLDEN_QUERIES_PATH, load_cases

    golden = load_cases(GOLDEN_QUERIES_PATH)
    examples = load_examples()
    if args.command == "approve":
        lines = REVIEW_LOG_PATH.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[args.log_line - 1])
        candidate = Example(args.id, record["query"], record["sql"])
        problems = contamination([candidate], golden, embed_question)
        if problems or any(e.id == candidate.id for e in examples):
            print("\n".join(problems) or f"id 중복: {candidate.id}")
            return 1
        save_examples(examples + [candidate])
        print(f"추가: {candidate.id}")
        return 0
    problems = contamination(examples, golden, embed_question)
    print(f"예시 {len(examples)}개, 문제 {len(problems)}건")
    print("\n".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
