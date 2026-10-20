"""Value candidates for the prompt: NER corrections plus an NER-independent n-gram search (spec 3.1)."""
from __future__ import annotations

import re
from dataclasses import dataclass

VALUE_COLUMNS = ("dept_name", "category", "subject_name", "professor", "class_mode", "eval_type", "grading_method")
# Same mapping as keyword_extract.ENTITY_REFERENCE_MAP (copied to avoid importing the NER model).
LABEL_TO_COLUMN = {
    "CATEGORY": "category",
    "COURSE_NAME": "subject_name",
    "DEPARTMENT": "dept_name",
    "CLASS_MODE": "class_mode",
    "EVAL_TYPE": "eval_type",
    "GRADE_METHOD": "grading_method",
    "PROFESSOR": "professor",
}
MIN_TOKEN_LENGTH = 3
MIN_FULL_LENGTH = 2


@dataclass(frozen=True)
class ValueCandidate:
    column: str
    value: str
    score: float
    source: str


def value_key(text) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(text or "")).lower()


def from_ner(entities: list[dict], references: dict[str, list[str]]) -> list[ValueCandidate]:
    found = []
    for entity in entities:
        column = LABEL_TO_COLUMN.get(entity.get("label"))
        value = entity.get("corrected_text")
        if column and value in references.get(column, ()):
            score = entity.get("similarity")
            found.append(ValueCandidate(column, value, float(score if score is not None else 100), "ner"))
    return found


def from_ngrams(question: str, references: dict[str, list[str]]) -> list[ValueCandidate]:
    question_key = value_key(question)
    found = []
    for column, values in references.items():
        keys = {value: value_key(value) for value in values}
        full_matches = {v: k for v, k in keys.items() if len(k) >= MIN_FULL_LENGTH and k in question_key}
        for value in values:
            full = full_matches.get(value)
            if full is not None:
                # '대면' also appears inside '비대면': keep only the longer value when both match.
                if not any(full != other and full in other for other in full_matches.values()):
                    found.append(ValueCandidate(column, value, 100.0, "ngram"))
                continue
            tokens = [value_key(t) for t in str(value).split()]
            if any(len(t) >= MIN_TOKEN_LENGTH and t in question_key for t in tokens):
                found.append(ValueCandidate(column, value, 90.0, "ngram"))
    return found


def from_hints(hints: list[dict]) -> list[ValueCandidate]:
    return [ValueCandidate(h["column"], h["value"], 100.0, "gold") for h in hints]


def merge(candidates: list[ValueCandidate], per_column: int = 3) -> list[ValueCandidate]:
    best: dict[tuple[str, str], ValueCandidate] = {}
    for candidate in candidates:
        key = (candidate.column, candidate.value)
        if key not in best or candidate.score > best[key].score:
            best[key] = candidate
    ordered: list[ValueCandidate] = []
    columns = list(VALUE_COLUMNS) + sorted({c.column for c in best.values()} - set(VALUE_COLUMNS))
    for column in columns:
        group = [c for c in best.values() if c.column == column]
        group.sort(key=lambda c: (-c.score, -len(c.value)))
        ordered.extend(group[:per_column])
    return ordered


def find_value_candidates(question, entities, references, sources) -> list[ValueCandidate]:
    found: list[ValueCandidate] = []
    if "ner" in sources:
        found += from_ner(entities or [], references)
    if "ngram" in sources:
        found += from_ngrams(question, references)
    return merge(found)


def load_value_references(fetch) -> dict[str, list[str]]:
    return {
        column: [r["v"] for r in fetch(f"SELECT DISTINCT {column} AS v FROM v_course_info WHERE {column} IS NOT NULL")]
        for column in VALUE_COLUMNS
    }
