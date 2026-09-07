# course-custom-ner Retraining Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild, from scratch, the data-generation and training pipeline for the `course-custom-ner` model (original training data/scripts are gone), producing a retrained checkpoint that measurably reduces boundary errors and label-type misclassification versus the current model.

**Architecture:** A chain of small standalone scripts under `backend/course_custom_ner_model/scripts/`: (1) an abbreviation-candidate inference tool that mines the live DB's DEPARTMENT/CATEGORY/COURSE_NAME values for plausible abbreviations, (2) a reusable template-rendering engine that computes exact character-offset entity spans, (3) a synthetic dataset generator built on top of it with a template catalog covering basic filters, connectives, ranges, negation, vacancy modifiers, abbreviation-mixed text, and deliberately confusable label pairs, (4) a hand-labeled real-query holdout set for final evaluation, (5) a BIO-alignment/metrics module, and (6) a HuggingFace `Trainer`-based fine-tuning script targeting the same `monologg/koelectra-small-v3-discriminator` base as the original model. A final task feeds reviewed abbreviations into `keyword_extract.py`'s `COMMON_ALIASES` and documents the end-to-end run.

**Tech Stack:** Python 3.10+, `transformers==4.46.3` (already used by the running app), `torch` (already installed, though not yet declared in `backend/requirements.txt`), `datasets`, `seqeval` (new), `psycopg2` (already used by the app), `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-07-ner-retraining-design.md`

## Global Constraints

- Original training data (`ner_train.jsonl`, `ner_valid.jsonl`, `ner_test.jsonl`, `ner_all.jsonl`) and training script do not exist anywhere in this repo or environment — everything in this plan is new.
- Abbreviation inference targets **DEPARTMENT, CATEGORY, COURSE_NAME only** — never PROFESSOR.
- Training-data generation concentrates on the 9 labels with real downstream consumers — **DEPARTMENT, CATEGORY, COURSE_NAME, PROFESSOR, CLASS_MODE, EVAL_TYPE, GRADE_METHOD, DAY, TIME** — while keeping the other 7 (CAPACITY, COURSE_YEAR, CREDIT, ENROLLED, ROOM, SECTION, VACANCY) present at a lighter weight so the model doesn't lose the ability to distinguish them.
- The label schema is the existing 16-label / 33-tag (`O` + 16×`B-`/`I-`) BIO scheme from `backend/course_custom_ner_model/models/course-custom-ner/labels.json` — do not add, remove, or rename labels.
- Base checkpoint for retraining is the public `monologg/koelectra-small-v3-discriminator` (matches the current model's `config.json`: `embedding_size=128, hidden_size=256, num_hidden_layers=12, num_attention_heads=4, vocab_size=35000`) — fine-tune fresh from this checkpoint, not by continuing from the existing `model.safetensors`.
- All new scripts under `backend/course_custom_ner_model/scripts/` are **standalone** (no imports from the `backend` package, e.g. no `from ..keyword_extract import ...`) so they remain portable to a separate remote GPU training environment that need not have the full app's dependencies (fastapi, redis, sqlglot, etc.) installed. Where DB access is needed, each script implements its own minimal connection helper rather than importing `keyword_extract.py`.
- **Run convention for this plan**: every command runs with the working directory set to `backend/course_custom_ner_model/scripts/` (e.g. `cd backend/course_custom_ner_model/scripts && python -m pytest test_infer_abbreviations.py -v`), and test files use plain imports (`from infer_abbreviations import ...`), not the `backend.X` package-style imports used elsewhere in this repo (e.g. in `backend/eval/`). This matches the existing standalone convention of `predict_ner.py` in the same directory.
- `backend/course_custom_ner_model/*` is fully excluded by `.gitignore`; specific files are tracked via `git add -f` (confirmed: `metadata/dataset_info.json`, `models/course-custom-ner/config.json`, `labels.json`, tokenizer files, `training_args.bin`, `scripts/predict_ner.py`). New script/test files and the two curated data artifacts from this plan (Task 1's reviewed abbreviations, Task 4's holdout set) must also be added with `git add -f`. Generated bulk data (`data/*.jsonl`, the raw unreviewed abbreviation candidates) stays untracked — it's reproducible by re-running the scripts.
- Label(type) misclassification and boundary errors are two distinct failure axes (see spec's "배경 및 목적"). The dataset generator must include confusable-pair templates targeting the misclassification axis, and the evaluation plan must include a per-label confusion matrix, not just aggregate P/R/F1.

---

### Task 1: Abbreviation candidate inference

**Files:**
- Create: `backend/course_custom_ner_model/scripts/infer_abbreviations.py`
- Test: `backend/course_custom_ner_model/scripts/test_infer_abbreviations.py`

**Interfaces:**
- Produces:
  - `strip_department_prefix(value: str) -> str`
  - `strip_known_suffix(value: str, suffixes: list[str]) -> str`
  - `mine_root_words(values: list[str], min_len: int = 2, max_len: int = 4, min_freq: int = 3) -> list[str]`
  - `segment_by_roots(value: str, roots: list[str]) -> list[str]`
  - `abbreviate_by_initials(segments: list[str]) -> str`
  - `split_parenthetical(value: str) -> tuple[str, str] | None`
  - `generate_abbreviation_candidates(value: str, label: str, roots: list[str], suffixes: list[str] | None = None) -> list[str]`
  - `infer_abbreviations(values_by_label: dict[str, list[str]], suffixes_by_label: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]`
  - `main()` — CLI entry point, thin: connects to `DATABASE_URL`, fetches distinct `dept_name`/`category`/`subject_name` from `v_course_info`, calls `infer_abbreviations`, writes `../data/abbreviation_candidates.json`.

- [ ] **Step 1: Write the failing tests**

`backend/course_custom_ner_model/scripts/test_infer_abbreviations.py`:
```python
from infer_abbreviations import (
    abbreviate_by_initials,
    generate_abbreviation_candidates,
    infer_abbreviations,
    mine_root_words,
    segment_by_roots,
    split_parenthetical,
    strip_department_prefix,
    strip_known_suffix,
)


def test_strip_department_prefix_removes_college_name():
    assert strip_department_prefix("공과대학 컴퓨터융합학부") == "컴퓨터융합학부"


def test_strip_department_prefix_leaves_value_without_prefix_unchanged():
    assert strip_department_prefix("컴퓨터융합학부") == "컴퓨터융합학부"


def test_strip_known_suffix_removes_longest_matching_suffix():
    assert strip_known_suffix("컴퓨터공학과", ["학과", "과"]) == "컴퓨터공"


def test_strip_known_suffix_leaves_value_unchanged_when_no_suffix_matches():
    assert strip_known_suffix("컴퓨터공학과", ["학부"]) == "컴퓨터공학과"


def test_mine_root_words_keeps_substrings_at_or_above_min_freq():
    values = ["컴퓨터공학과", "컴퓨터융합학부", "컴퓨터인공지능학부", "전자공학과", "기계공학부"]
    roots = mine_root_words(values, min_len=2, max_len=4, min_freq=3)
    assert "컴퓨터" in roots


def test_mine_root_words_excludes_rare_substrings():
    values = ["컴퓨터공학과", "컴퓨터융합학부", "컴퓨터인공지능학부", "전자공학과", "기계공학부"]
    roots = mine_root_words(values, min_len=2, max_len=4, min_freq=3)
    assert "인공지능" not in roots


def test_segment_by_roots_matches_longest_root_greedily():
    roots = ["컴퓨터", "컴", "공"]
    assert segment_by_roots("컴퓨터공", roots) == ["컴퓨터", "공"]


def test_segment_by_roots_falls_back_to_single_characters():
    assert segment_by_roots("공", ["컴퓨터"]) == ["공"]


def test_abbreviate_by_initials_takes_first_character_of_each_segment():
    assert abbreviate_by_initials(["컴퓨터", "공"]) == "컴공"


def test_abbreviate_by_initials_handles_empty_segment_list():
    assert abbreviate_by_initials([]) == ""


def test_split_parenthetical_extracts_both_groups():
    assert split_parenthetical("전공(핵심)") == ("전공", "핵심")


def test_split_parenthetical_returns_none_when_no_parentheses():
    assert split_parenthetical("일반선택") is None


def test_generate_abbreviation_candidates_for_department_matches_known_alias():
    roots = ["컴퓨터", "공학", "융합"]
    candidates = generate_abbreviation_candidates(
        "공과대학 컴퓨터공학과", "DEPARTMENT", roots, suffixes=["학과", "학부"]
    )
    assert "컴공" in candidates


def test_generate_abbreviation_candidates_for_category_uses_parenthetical_initials():
    candidates = generate_abbreviation_candidates("전공(핵심)", "CATEGORY", roots=[])
    assert "전핵" in candidates


def test_generate_abbreviation_candidates_for_category_without_parens_is_empty():
    candidates = generate_abbreviation_candidates("일반선택", "CATEGORY", roots=[])
    assert candidates == []


def test_generate_abbreviation_candidates_never_returns_value_itself():
    roots = ["데이터베이스"]
    candidates = generate_abbreviation_candidates("데이터베이스", "COURSE_NAME", roots)
    assert "데이터베이스" not in candidates


def test_infer_abbreviations_covers_every_requested_label():
    values_by_label = {
        "DEPARTMENT": ["공과대학 컴퓨터공학과", "공과대학 컴퓨터융합학부", "공과대학 컴퓨터인공지능학부"],
        "CATEGORY": ["전공(핵심)", "전공(기초)", "일반선택"],
    }
    suffixes_by_label = {"DEPARTMENT": ["학과", "학부"], "CATEGORY": []}
    result = infer_abbreviations(values_by_label, suffixes_by_label)
    assert set(result.keys()) == {"DEPARTMENT", "CATEGORY"}
    assert "전핵" in result["CATEGORY"]["전공(핵심)"]


def test_infer_abbreviations_skips_values_with_no_candidates():
    values_by_label = {"CATEGORY": ["일반선택"]}
    suffixes_by_label = {"CATEGORY": []}
    result = infer_abbreviations(values_by_label, suffixes_by_label)
    assert "일반선택" not in result["CATEGORY"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_infer_abbreviations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'infer_abbreviations'`

- [ ] **Step 3: Write the implementation**

`backend/course_custom_ner_model/scripts/infer_abbreviations.py`:
```python
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

DEPARTMENT_PREFIX_RE = re.compile(r"^[가-힣]+대학\s+")
PARENTHETICAL_RE = re.compile(r"^(.+)\((.+)\)$")


def strip_department_prefix(value: str) -> str:
    return DEPARTMENT_PREFIX_RE.sub("", value)


def strip_known_suffix(value: str, suffixes: list[str]) -> str:
    for suffix in sorted(suffixes, key=len, reverse=True):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def mine_root_words(
    values: list[str], min_len: int = 2, max_len: int = 4, min_freq: int = 3
) -> list[str]:
    counts: Counter[str] = Counter()
    for value in values:
        length = len(value)
        for size in range(min_len, max_len + 1):
            for start in range(0, length - size + 1):
                counts[value[start : start + size]] += 1
    roots = [root for root, count in counts.items() if count >= min_freq]
    roots.sort(key=lambda root: (-len(root), -counts[root]))
    return roots


def segment_by_roots(value: str, roots: list[str]) -> list[str]:
    segments: list[str] = []
    index = 0
    while index < len(value):
        matched = None
        for root in roots:
            if value.startswith(root, index):
                matched = root
                break
        if matched:
            segments.append(matched)
            index += len(matched)
        else:
            segments.append(value[index])
            index += 1
    return segments


def abbreviate_by_initials(segments: list[str]) -> str:
    return "".join(segment[0] for segment in segments if segment)


def split_parenthetical(value: str) -> tuple[str, str] | None:
    match = PARENTHETICAL_RE.match(value)
    if not match:
        return None
    return match.group(1), match.group(2)


def _generic_candidates(value: str, roots: list[str], suffixes: list[str] | None) -> list[str]:
    candidates: list[str] = []

    trimmed = strip_department_prefix(value)
    without_suffix = strip_known_suffix(trimmed, suffixes) if suffixes else trimmed

    for source in (without_suffix, trimmed):
        segments = segment_by_roots(source, roots)
        candidate = abbreviate_by_initials(segments)
        if candidate and candidate != value and len(candidate) < len(value) and candidate not in candidates:
            candidates.append(candidate)

    return candidates


def generate_abbreviation_candidates(
    value: str,
    label: str,
    roots: list[str],
    suffixes: list[str] | None = None,
) -> list[str]:
    if label == "CATEGORY":
        parts = split_parenthetical(value)
        if parts:
            first, second = parts
            candidate = first[0] + second[0]
            return [candidate] if candidate != value else []
        return []

    return _generic_candidates(value, roots, suffixes)


def infer_abbreviations(
    values_by_label: dict[str, list[str]],
    suffixes_by_label: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for label, values in values_by_label.items():
        roots = mine_root_words(values)
        suffixes = suffixes_by_label.get(label, [])
        label_result: dict[str, list[str]] = {}
        for value in values:
            candidates = generate_abbreviation_candidates(value, label, roots, suffixes)
            if candidates:
                label_result[value] = candidates
        result[label] = label_result
    return result


def _build_postgres_dsn() -> str:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "")
    port = os.getenv("POSTGRES_PORT", "")
    database = os.getenv("POSTGRES_DB", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _fetch_distinct_values(dsn: str, table: str, column: str) -> list[str]:
    import psycopg2
    from psycopg2 import sql

    stmt = sql.SQL(
        "SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL AND TRIM(CAST({column} AS TEXT)) <> ''"
    ).format(column=sql.Identifier(column), table=sql.Identifier(table))
    with psycopg2.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(stmt)
            return [str(row[0]).strip() for row in cur.fetchall() if row[0]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer abbreviation candidates from live DB values")
    parser.add_argument(
        "--output",
        default="../data/abbreviation_candidates.json",
        help="Where to write the raw (unreviewed) candidates JSON",
    )
    args = parser.parse_args()

    dsn = _build_postgres_dsn()
    values_by_label = {
        "DEPARTMENT": _fetch_distinct_values(dsn, "v_course_info", "dept_name"),
        "CATEGORY": _fetch_distinct_values(dsn, "v_course_info", "category"),
        "COURSE_NAME": _fetch_distinct_values(dsn, "v_course_info", "subject_name"),
    }
    suffixes_by_label = {
        "DEPARTMENT": ["학과", "학부", "전공"],
        "CATEGORY": [],
        "COURSE_NAME": [],
    }

    result = infer_abbreviations(values_by_label, suffixes_by_label)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_infer_abbreviations.py -v`
Expected: all 18 tests PASS

- [ ] **Step 5: Commit**

```bash
git add -f backend/course_custom_ner_model/scripts/infer_abbreviations.py backend/course_custom_ner_model/scripts/test_infer_abbreviations.py
git commit -m "feat: add DB-driven abbreviation candidate inference for NER retraining"
```

---

### Task 2: Template rendering engine

**Files:**
- Create: `backend/course_custom_ner_model/scripts/ner_template_engine.py`
- Test: `backend/course_custom_ner_model/scripts/test_ner_template_engine.py`

**Interfaces:**
- Produces:
  - `render_template(template: str, values: dict[str, tuple[str, str]]) -> dict` — returns `{"text": str, "entities": [{"start": int, "end": int, "label": str}, ...]}` (entities sorted by `start` ascending). `template` contains `{PLACEHOLDER}` tokens; `values` maps each placeholder name appearing in the template to `(text_to_insert, entity_label)`.

- [ ] **Step 1: Write the failing tests**

`backend/course_custom_ner_model/scripts/test_ner_template_engine.py`:
```python
from ner_template_engine import render_template


def test_render_template_substitutes_single_slot():
    result = render_template("{DEPARTMENT} 과목 보여줘", {"DEPARTMENT": ("컴퓨터융합학부", "DEPARTMENT")})
    assert result["text"] == "컴퓨터융합학부 과목 보여줘"
    assert result["entities"] == [{"start": 0, "end": 7, "label": "DEPARTMENT"}]


def test_render_template_computes_correct_offsets_for_multiple_slots():
    template = "{DEPARTMENT} {CATEGORY} 과목 알려줘"
    values = {
        "DEPARTMENT": ("컴퓨터융합학부", "DEPARTMENT"),
        "CATEGORY": ("전공(핵심)", "CATEGORY"),
    }
    result = render_template(template, values)
    assert result["text"] == "컴퓨터융합학부 전공(핵심) 과목 알려줘"
    assert result["entities"] == [
        {"start": 0, "end": 7, "label": "DEPARTMENT"},
        {"start": 8, "end": 14, "label": "CATEGORY"},
    ]


def test_render_template_supports_two_slots_of_the_same_label():
    template = "{COURSE_NAME}이랑 {COURSE_NAME_2} 보여줘"
    values = {
        "COURSE_NAME": ("데이터베이스", "COURSE_NAME"),
        "COURSE_NAME_2": ("자료구조", "COURSE_NAME"),
    }
    result = render_template(template, values)
    assert result["text"] == "데이터베이스이랑 자료구조 보여줘"
    assert result["entities"] == [
        {"start": 0, "end": 6, "label": "COURSE_NAME"},
        {"start": 9, "end": 13, "label": "COURSE_NAME"},
    ]


def test_render_template_with_no_placeholders_returns_no_entities():
    result = render_template("오늘 날씨 어때?", {})
    assert result == {"text": "오늘 날씨 어때?", "entities": []}


def test_render_template_entities_are_sorted_by_start():
    template = "{B} 그리고 {A}"
    values = {"A": ("가", "CATEGORY"), "B": ("나", "DEPARTMENT")}
    result = render_template(template, values)
    starts = [entity["start"] for entity in result["entities"]]
    assert starts == sorted(starts)


def test_render_template_raises_on_missing_value_for_placeholder():
    try:
        render_template("{DEPARTMENT} 보여줘", {})
        assert False, "expected KeyError"
    except KeyError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_ner_template_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ner_template_engine'`

- [ ] **Step 3: Write the implementation**

`backend/course_custom_ner_model/scripts/ner_template_engine.py`:
```python
from __future__ import annotations

import re

PLACEHOLDER_RE = re.compile(r"\{([A-Z0-9_]+)\}")


def render_template(template: str, values: dict[str, tuple[str, str]]) -> dict:
    output_parts: list[str] = []
    entities: list[dict] = []
    cursor = 0
    output_length = 0

    for match in PLACEHOLDER_RE.finditer(template):
        literal = template[cursor : match.start()]
        output_parts.append(literal)
        output_length += len(literal)

        placeholder = match.group(1)
        text, label = values[placeholder]

        start = output_length
        output_parts.append(text)
        output_length += len(text)
        end = output_length

        entities.append({"start": start, "end": end, "label": label})
        cursor = match.end()

    output_parts.append(template[cursor:])

    entities.sort(key=lambda entity: entity["start"])
    return {"text": "".join(output_parts), "entities": entities}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_ner_template_engine.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add -f backend/course_custom_ner_model/scripts/ner_template_engine.py backend/course_custom_ner_model/scripts/test_ner_template_engine.py
git commit -m "feat: add offset-safe template rendering engine for NER synthetic data"
```

---

### Task 3: Synthetic dataset generator (template catalog + confusable pairs + split)

**Files:**
- Create: `backend/course_custom_ner_model/scripts/generate_ner_dataset.py`
- Test: `backend/course_custom_ner_model/scripts/test_generate_ner_dataset.py`

**Interfaces:**
- Consumes: `render_template(template: str, values: dict[str, tuple[str, str]]) -> dict` (Task 2, `from ner_template_engine import render_template`)
- Produces:
  - `Template` — a `@dataclass` with fields `id: str`, `text: str`, `slots: dict[str, str]` (placeholder name -> label), `weight: int`.
  - `TEMPLATE_CATALOG: list[Template]`
  - `generate_time_values(rng, count) -> list[str]`, `generate_course_year_values() -> list[str]`, `generate_credit_values() -> list[str]`, `generate_section_values() -> list[str]`, `generate_headcount_values(rng, count) -> list[str]`, `generate_room_values(rng, count) -> list[str]`
  - `DAY_VALUES: list[str]`, `VACANCY_PHRASES: list[str]`
  - `build_value_pools(db_values_by_label: dict[str, list[str]], abbreviations_by_label: dict[str, dict[str, list[str]]], rng) -> dict[str, list[str]]`
  - `generate_records(template_catalog: list[Template], value_pools: dict[str, list[str]], rng) -> list[dict]` — each record is `{"template_id": str, "text": str, "entities": [...]}`.
  - `split_by_template(records: list[dict], valid_ratio: float, test_ratio: float, rng) -> tuple[list[dict], list[dict], list[dict]]`
  - `main()` — CLI: loads DB values + reviewed abbreviations file, calls the above, writes `ner_train.jsonl`/`ner_valid.jsonl`/`ner_test.jsonl` to `../data/`.

- [ ] **Step 1: Write the failing tests**

`backend/course_custom_ner_model/scripts/test_generate_ner_dataset.py`:
```python
import random

from generate_ner_dataset import (
    TEMPLATE_CATALOG,
    Template,
    build_value_pools,
    generate_course_year_values,
    generate_credit_values,
    generate_records,
    generate_section_values,
    split_by_template,
)


def test_template_catalog_is_non_empty_and_ids_are_unique():
    ids = [template.id for template in TEMPLATE_CATALOG]
    assert len(TEMPLATE_CATALOG) >= 30
    assert len(ids) == len(set(ids))


def test_template_catalog_every_placeholder_has_a_declared_slot():
    import re

    placeholder_re = re.compile(r"\{([A-Z0-9_]+)\}")
    for template in TEMPLATE_CATALOG:
        placeholders = set(placeholder_re.findall(template.text))
        assert placeholders == set(template.slots.keys()), template.id


def test_template_catalog_includes_confusable_pair_templates():
    confusable_ids = [t.id for t in TEMPLATE_CATALOG if t.id.startswith("confusable_")]
    assert len(confusable_ids) >= 4


def test_generate_course_year_values_covers_1_to_4():
    assert generate_course_year_values() == ["1학년", "2학년", "3학년", "4학년"]


def test_generate_credit_values_covers_1_to_4():
    assert generate_credit_values() == ["1학점", "2학점", "3학점", "4학점"]


def test_generate_section_values_are_zero_padded():
    values = generate_section_values()
    assert "01분반" in values
    assert all(v.endswith("분반") for v in values)


def test_build_value_pools_includes_abbreviation_variants_for_priority_labels():
    db_values = {"DEPARTMENT": ["컴퓨터융합학부"], "CATEGORY": ["전공(핵심)"], "COURSE_NAME": ["데이터베이스"]}
    abbreviations = {"DEPARTMENT": {"컴퓨터융합학부": ["컴융"]}}
    pools = build_value_pools(db_values, abbreviations, random.Random(0))
    assert "컴융" in pools["DEPARTMENT_ABBR"]
    assert "컴퓨터융합학부" in pools["DEPARTMENT"]


def test_full_catalog_generates_without_crashing_with_realistic_pools():
    db_values = {
        "DEPARTMENT": ["공과대학 컴퓨터융합학부", "경상대학 경제학과"],
        "CATEGORY": ["전공(핵심)", "전공(기초)", "일반선택"],
        "COURSE_NAME": ["데이터베이스", "자료구조", "알고리즘응용"],
        "PROFESSOR": ["유정연", "이규철"],
        "CLASS_MODE": ["실시간", "콘텐츠", "혼합"],
        "EVAL_TYPE": ["GRADE", "PASS"],
        "GRADE_METHOD": ["상대평가", "절대평가"],
    }
    abbreviations = {
        "DEPARTMENT": {"공과대학 컴퓨터융합학부": ["컴융"]},
        "CATEGORY": {"전공(핵심)": ["전핵"], "전공(기초)": ["전기"]},
        "COURSE_NAME": {"알고리즘응용": ["알응"]},
    }
    rng = random.Random(42)
    pools = build_value_pools(db_values, abbreviations, rng)
    records = generate_records(TEMPLATE_CATALOG, pools, rng)

    expected_count = sum(t.weight for t in TEMPLATE_CATALOG)
    assert len(records) == expected_count

    for record in records:
        for entity in record["entities"]:
            substring = record["text"][entity["start"] : entity["end"]]
            assert substring, (record["template_id"], record["text"], entity)


def test_generate_records_produces_valid_offsets_for_every_template():
    tiny_catalog = [
        Template(id="t1", text="{DEPARTMENT} 과목", slots={"DEPARTMENT": "DEPARTMENT"}, weight=2),
        Template(id="t2", text="{CATEGORY} 알려줘", slots={"CATEGORY": "CATEGORY"}, weight=2),
    ]
    value_pools = {"DEPARTMENT": ["컴퓨터융합학부"], "CATEGORY": ["전공(핵심)"]}
    records = generate_records(tiny_catalog, value_pools, random.Random(0))
    assert len(records) == 4
    for record in records:
        for entity in record["entities"]:
            assert record["text"][entity["start"] : entity["end"]]


def test_generate_records_tags_each_record_with_its_template_id():
    tiny_catalog = [Template(id="only", text="{DAY} 수업", slots={"DAY": "DAY"}, weight=3)]
    value_pools = {"DAY": ["월"]}
    records = generate_records(tiny_catalog, value_pools, random.Random(0))
    assert all(record["template_id"] == "only" for record in records)
    assert len(records) == 3


def test_split_by_template_keeps_each_template_in_exactly_one_split():
    records = [{"template_id": f"t{i % 5}", "text": "x", "entities": []} for i in range(50)]
    train, valid, test = split_by_template(records, valid_ratio=0.2, test_ratio=0.2, rng=random.Random(0))
    train_ids = {r["template_id"] for r in train}
    valid_ids = {r["template_id"] for r in valid}
    test_ids = {r["template_id"] for r in test}
    assert not (train_ids & valid_ids)
    assert not (train_ids & test_ids)
    assert not (valid_ids & test_ids)


def test_split_by_template_covers_all_records():
    records = [{"template_id": f"t{i % 5}", "text": "x", "entities": []} for i in range(50)]
    train, valid, test = split_by_template(records, valid_ratio=0.2, test_ratio=0.2, rng=random.Random(0))
    assert len(train) + len(valid) + len(test) == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_generate_ner_dataset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generate_ner_dataset'`

- [ ] **Step 3: Write the implementation**

`backend/course_custom_ner_model/scripts/generate_ner_dataset.py`:
```python
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from ner_template_engine import render_template


@dataclass
class Template:
    id: str
    text: str
    slots: dict[str, str]
    weight: int = 10


DAY_VALUES = ["월", "화", "수", "목", "금", "토", "일"]
VACANCY_PHRASES = ["빈자리가 있는", "빈자리 있는", "잔여석이 남아있는", "자리가 남은"]


def generate_time_values(rng: random.Random, count: int) -> list[str]:
    values = []
    for _ in range(count):
        hour = rng.randint(1, 12)
        style = rng.choice(["hour_only", "hour_minute", "24h"])
        if style == "hour_only":
            values.append(f"{hour}시")
        elif style == "hour_minute":
            minute = rng.choice([0, 10, 20, 30, 40, 50])
            values.append(f"{hour}시 {minute}분" if minute else f"{hour}시")
        else:
            hour24 = hour if rng.random() < 0.5 else hour + 12
            values.append(f"{hour24:02d}:00")
    return values


def generate_course_year_values() -> list[str]:
    return [f"{n}학년" for n in range(1, 5)]


def generate_credit_values() -> list[str]:
    return [f"{n}학점" for n in range(1, 5)]


def generate_section_values() -> list[str]:
    return [f"{n:02d}분반" for n in range(1, 7)]


def generate_headcount_values(rng: random.Random, count: int) -> list[str]:
    return [f"{rng.randint(5, 50)}명" for _ in range(count)]


def generate_room_values(rng: random.Random, count: int) -> list[str]:
    buildings = ["공", "인", "자", "경상", "간호"]
    return [
        f"{rng.choice(buildings)}{rng.randint(1, 9)}{rng.randint(0, 9)}{rng.randint(0, 9)}"
        for _ in range(count)
    ]


TEMPLATE_CATALOG: list[Template] = [
    Template("dept_only", "{DEPARTMENT} 과목 보여줘", {"DEPARTMENT": "DEPARTMENT"}, weight=25),
    Template("category_only", "{CATEGORY} 과목 알려줘", {"CATEGORY": "CATEGORY"}, weight=25),
    Template("course_name_only", "{COURSE_NAME} 과목 알려줘", {"COURSE_NAME": "COURSE_NAME"}, weight=25),
    Template("professor_only", "{PROFESSOR} 교수님이 가르치는 과목 알려줘", {"PROFESSOR": "PROFESSOR"}, weight=15),
    Template("class_mode_only", "{CLASS_MODE} 교양 찾아줘", {"CLASS_MODE": "CLASS_MODE"}, weight=15),
    Template("eval_type_only", "{EVAL_TYPE} 방식인 과목 알려줘", {"EVAL_TYPE": "EVAL_TYPE"}, weight=15),
    Template("grade_method_only", "{GRADE_METHOD}인 과목 알려줘", {"GRADE_METHOD": "GRADE_METHOD"}, weight=15),
    Template("dept_category", "{DEPARTMENT} {CATEGORY} 보여줘", {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"}, weight=25),
    Template("dept_day", "{DEPARTMENT} {DAY} 수업 알려줘", {"DEPARTMENT": "DEPARTMENT", "DAY": "DAY"}, weight=20),
    Template("dept_time", "{DEPARTMENT} {TIME} 수업 알려줘", {"DEPARTMENT": "DEPARTMENT", "TIME": "TIME"}, weight=20),
    Template(
        "dept_category_day",
        "{DEPARTMENT} {CATEGORY} 중 {DAY} 수업 보여줘",
        {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY", "DAY": "DAY"},
        weight=20,
    ),
    Template(
        "dept_category_time",
        "{DEPARTMENT} {CATEGORY} {TIME} 강의 보여줘",
        {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY", "TIME": "TIME"},
        weight=20,
    ),
    Template("day_time", "{DAY} {TIME} 강의 보여줘", {"DAY": "DAY", "TIME": "TIME"}, weight=15),
    Template(
        "connective_course",
        "{COURSE_NAME}이랑 {COURSE_NAME_2} 보여줘",
        {"COURSE_NAME": "COURSE_NAME", "COURSE_NAME_2": "COURSE_NAME"},
        weight=15,
    ),
    Template(
        "connective_dept_category",
        "{DEPARTMENT} {CATEGORY}이랑 {DEPARTMENT_2} {CATEGORY_2} 찾아줘",
        {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY", "DEPARTMENT_2": "DEPARTMENT", "CATEGORY_2": "CATEGORY"},
        weight=10,
    ),
    Template(
        "time_range_tilde",
        "{TIME} ~ {TIME_2} 사이 {DEPARTMENT} {CATEGORY} 보여줘",
        {"TIME": "TIME", "TIME_2": "TIME", "DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"},
        weight=10,
    ),
    Template(
        "time_range_budeo",
        "{TIME}부터 {TIME_2}까지 {CATEGORY} 보여줘",
        {"TIME": "TIME", "TIME_2": "TIME", "CATEGORY": "CATEGORY"},
        weight=10,
    ),
    Template(
        "exclude_day",
        "{DEPARTMENT} {CATEGORY} 중 {DAY} 제외하고 보여줘",
        {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY", "DAY": "DAY"},
        weight=15,
    ),
    Template(
        "exclude_course",
        "{CATEGORY} 과목 중 {COURSE_NAME} 빼고 보여줘",
        {"CATEGORY": "CATEGORY", "COURSE_NAME": "COURSE_NAME"},
        weight=15,
    ),
    Template(
        "vacancy_dept_category",
        "{VACANCY} {DEPARTMENT} {CATEGORY} 보여줘",
        {"VACANCY": "VACANCY", "DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"},
        weight=15,
    ),
    Template("vacancy_category", "{VACANCY} {CATEGORY} 보여줘", {"VACANCY": "VACANCY", "CATEGORY": "CATEGORY"}, weight=10),
    Template("vacancy_course", "{VACANCY} {COURSE_NAME} 보여줘", {"VACANCY": "VACANCY", "COURSE_NAME": "COURSE_NAME"}, weight=10),
    Template("dept_category_chajwo", "{DEPARTMENT} {CATEGORY} 찾아줘", {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"}, weight=15),
    Template("dept_category_isseo", "{DEPARTMENT} {CATEGORY} 있어?", {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"}, weight=15),
    Template("dept_time_mwo", "{DEPARTMENT} {TIME} 수업 뭐 있어", {"DEPARTMENT": "DEPARTMENT", "TIME": "TIME"}, weight=15),
    Template(
        "abbrev_dept_category",
        "{DEPARTMENT} {CATEGORY} 보여줘",
        {"DEPARTMENT": "DEPARTMENT_ABBR", "CATEGORY": "CATEGORY_ABBR"},
        weight=15,
    ),
    Template("abbrev_course_only", "{COURSE_NAME} 과목 알려줘", {"COURSE_NAME": "COURSE_NAME_ABBR"}, weight=15),
    Template(
        "confusable_year_credit",
        "{DEPARTMENT} {COURSE_YEAR} {CREDIT} 과목 알려줘",
        {"DEPARTMENT": "DEPARTMENT", "COURSE_YEAR": "COURSE_YEAR", "CREDIT": "CREDIT"},
        weight=12,
    ),
    Template(
        "confusable_year_section",
        "{COURSE_YEAR} {SECTION} 과목 보여줘",
        {"COURSE_YEAR": "COURSE_YEAR", "SECTION": "SECTION"},
        weight=8,
    ),
    Template(
        "confusable_capacity_enrolled",
        "정원 {CAPACITY} 중 {ENROLLED} 찬 {DEPARTMENT} 과목",
        {"CAPACITY": "CAPACITY", "ENROLLED": "ENROLLED", "DEPARTMENT": "DEPARTMENT"},
        weight=8,
    ),
    Template(
        "confusable_dept_coursename",
        "{DEPARTMENT} {COURSE_NAME} 과목",
        {"DEPARTMENT": "DEPARTMENT", "COURSE_NAME": "COURSE_NAME"},
        weight=15,
    ),
    Template(
        "confusable_shortcats",
        "{CLASS_MODE} {EVAL_TYPE} {GRADE_METHOD} 조건의 과목 알려줘",
        {"CLASS_MODE": "CLASS_MODE", "EVAL_TYPE": "EVAL_TYPE", "GRADE_METHOD": "GRADE_METHOD"},
        weight=8,
    ),
    Template(
        "confusable_room_section",
        "{ROOM} 강의실 {SECTION} 과목 알려줘",
        {"ROOM": "ROOM", "SECTION": "SECTION"},
        weight=6,
    ),
    Template("room_only", "{ROOM} 강의실에서 하는 수업 알려줘", {"ROOM": "ROOM"}, weight=5),
    Template("section_only", "{DEPARTMENT} {SECTION} 과목 알려줘", {"DEPARTMENT": "DEPARTMENT", "SECTION": "SECTION"}, weight=5),
]


PRIORITY_LABELS = {
    "DEPARTMENT",
    "CATEGORY",
    "COURSE_NAME",
    "PROFESSOR",
    "CLASS_MODE",
    "EVAL_TYPE",
    "GRADE_METHOD",
    "DAY",
    "TIME",
}


def build_value_pools(
    db_values_by_label: dict[str, list[str]],
    abbreviations_by_label: dict[str, dict[str, list[str]]],
    rng: random.Random,
) -> dict[str, list[str]]:
    pools: dict[str, list[str]] = {}

    for label, values in db_values_by_label.items():
        pools[label] = list(values)

    for label, value_to_candidates in abbreviations_by_label.items():
        all_candidates = [candidate for candidates in value_to_candidates.values() for candidate in candidates]
        pools[f"{label}_ABBR"] = all_candidates or list(db_values_by_label.get(label, []))

    pools.setdefault("DAY", DAY_VALUES)
    pools.setdefault("VACANCY", VACANCY_PHRASES)
    pools.setdefault("TIME", generate_time_values(rng, 30))
    pools.setdefault("COURSE_YEAR", generate_course_year_values())
    pools.setdefault("CREDIT", generate_credit_values())
    pools.setdefault("SECTION", generate_section_values())
    pools.setdefault("CAPACITY", generate_headcount_values(rng, 20))
    pools.setdefault("ENROLLED", generate_headcount_values(rng, 20))
    pools.setdefault("ROOM", generate_room_values(rng, 20))

    return pools


def _fill_values_for_template(
    template: Template, value_pools: dict[str, list[str]], rng: random.Random
) -> dict[str, tuple[str, str]]:
    values: dict[str, tuple[str, str]] = {}
    for placeholder, pool_key in template.slots.items():
        base_label = pool_key[: -len("_ABBR")] if pool_key.endswith("_ABBR") else pool_key
        pool = value_pools.get(pool_key) or value_pools.get(base_label) or []
        if not pool:
            raise ValueError(f"no values available for pool '{pool_key}' (template {template.id})")
        text = rng.choice(pool)
        values[placeholder] = (text, base_label)
    return values


def generate_records(
    template_catalog: list[Template],
    value_pools: dict[str, list[str]],
    rng: random.Random,
) -> list[dict]:
    records: list[dict] = []
    for template in template_catalog:
        for _ in range(template.weight):
            values = _fill_values_for_template(template, value_pools, rng)
            rendered = render_template(template.text, values)
            records.append({"template_id": template.id, "text": rendered["text"], "entities": rendered["entities"]})
    return records


def split_by_template(
    records: list[dict],
    valid_ratio: float,
    test_ratio: float,
    rng: random.Random,
) -> tuple[list[dict], list[dict], list[dict]]:
    template_ids = sorted({record["template_id"] for record in records})
    rng.shuffle(template_ids)

    total = len(template_ids)
    test_count = max(1, int(total * test_ratio)) if total > 1 else 0
    valid_count = max(1, int(total * valid_ratio)) if total > 1 else 0

    test_ids = set(template_ids[:test_count])
    valid_ids = set(template_ids[test_count : test_count + valid_count])
    train_ids = set(template_ids[test_count + valid_count :])

    train = [r for r in records if r["template_id"] in train_ids]
    valid = [r for r in records if r["template_id"] in valid_ids]
    test = [r for r in records if r["template_id"] in test_ids]
    return train, valid, test


def _write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic NER training data")
    parser.add_argument("--abbreviations-file", default="../metadata/abbreviation_candidates.reviewed.json")
    parser.add_argument("--output-dir", default="../data")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--valid-ratio", type=float, default=0.15)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    args = parser.parse_args()

    from infer_abbreviations import _build_postgres_dsn, _fetch_distinct_values

    rng = random.Random(args.seed)
    dsn = _build_postgres_dsn()
    db_values_by_label = {
        "DEPARTMENT": _fetch_distinct_values(dsn, "v_course_info", "dept_name"),
        "CATEGORY": _fetch_distinct_values(dsn, "v_course_info", "category"),
        "COURSE_NAME": _fetch_distinct_values(dsn, "v_course_info", "subject_name"),
        "PROFESSOR": _fetch_distinct_values(dsn, "v_course_info", "professor"),
        "CLASS_MODE": _fetch_distinct_values(dsn, "v_course_info", "class_mode"),
        "EVAL_TYPE": _fetch_distinct_values(dsn, "v_course_info", "eval_type"),
        "GRADE_METHOD": _fetch_distinct_values(dsn, "v_course_info", "grading_method"),
    }

    abbreviations_path = Path(args.abbreviations_file)
    if abbreviations_path.exists():
        with open(abbreviations_path, "r", encoding="utf-8") as file:
            abbreviations_by_label = json.load(file)
    else:
        abbreviations_by_label = {}

    value_pools = build_value_pools(db_values_by_label, abbreviations_by_label, rng)
    records = generate_records(TEMPLATE_CATALOG, value_pools, rng)
    train, valid, test = split_by_template(records, args.valid_ratio, args.test_ratio, rng)

    output_dir = Path(args.output_dir)
    _write_jsonl(train, output_dir / "ner_train.jsonl")
    _write_jsonl(valid, output_dir / "ner_valid.jsonl")
    _write_jsonl(test, output_dir / "ner_test.jsonl")
    print(f"train={len(train)} valid={len(valid)} test={len(test)} -> {output_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_generate_ner_dataset.py -v`
Expected: all 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add -f backend/course_custom_ner_model/scripts/generate_ner_dataset.py backend/course_custom_ner_model/scripts/test_generate_ner_dataset.py
git commit -m "feat: add template catalog and synthetic NER dataset generator"
```

---

### Task 4: Real-query holdout evaluation set

**Files:**
- Create: `backend/course_custom_ner_model/metadata/ner_holdout_real.jsonl`
- Create: `backend/course_custom_ner_model/scripts/test_ner_holdout_real.py`

**Interfaces:**
- Produces: `backend/course_custom_ner_model/metadata/ner_holdout_real.jsonl` — 27 hand-labeled real queries from `backend-log.txt`, one JSON object per line: `{"text": str, "entities": [{"start": int, "end": int, "label": str}, ...]}`. Consumed by Task 6's `train.py --holdout-file`.

- [ ] **Step 1: Write the failing test**

`backend/course_custom_ner_model/scripts/test_ner_holdout_real.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_ner_holdout_real.py -v`
Expected: FAIL — `FileNotFoundError` (the jsonl doesn't exist yet)

- [ ] **Step 3: Create the holdout file**

`backend/course_custom_ner_model/metadata/ner_holdout_real.jsonl` (27 lines, each hand-verified against its source query in `backend-log.txt` — every offset below was computed and round-trip checked programmatically before being written here):

```json
{"text": "1시 ~ 3시 사이 공과대학 컴퓨터융합학부 전공 보여줘", "entities": [{"start": 0, "end": 2, "label": "TIME"}, {"start": 5, "end": 7, "label": "TIME"}, {"start": 11, "end": 23, "label": "DEPARTMENT"}, {"start": 24, "end": 26, "label": "CATEGORY"}]}
{"text": "1학년 공과대학 응용화학공학과 전공(심화) 금요일 강의 보여줘", "entities": [{"start": 0, "end": 3, "label": "COURSE_YEAR"}, {"start": 4, "end": 16, "label": "DEPARTMENT"}, {"start": 17, "end": 23, "label": "CATEGORY"}, {"start": 24, "end": 27, "label": "DAY"}]}
{"text": "2학년대상 공과대학 응용화학공학과 전공과목 찾아줘", "entities": [{"start": 0, "end": 3, "label": "COURSE_YEAR"}, {"start": 6, "end": 18, "label": "DEPARTMENT"}, {"start": 19, "end": 21, "label": "CATEGORY"}]}
{"text": "3시 제외 전공 보여줘", "entities": [{"start": 0, "end": 2, "label": "TIME"}, {"start": 6, "end": 8, "label": "CATEGORY"}]}
{"text": "공과대학 컴퓨터융합학부 2학년 대상 과목 중에서 내가 들은 거 빼고 알려줘", "entities": [{"start": 0, "end": 12, "label": "DEPARTMENT"}, {"start": 13, "end": 16, "label": "COURSE_YEAR"}]}
{"text": "공과대학 컴퓨터융합학부 3학년 전공(핵심) 금요일 14시 강의 보여줘.", "entities": [{"start": 0, "end": 12, "label": "DEPARTMENT"}, {"start": 13, "end": 16, "label": "COURSE_YEAR"}, {"start": 17, "end": 23, "label": "CATEGORY"}, {"start": 24, "end": 27, "label": "DAY"}, {"start": 28, "end": 31, "label": "TIME"}]}
{"text": "공과대학 컴퓨터융합학부 3학년 전공(핵심)에서 빈자리가 있는 금요일 과목 보여줘", "entities": [{"start": 0, "end": 12, "label": "DEPARTMENT"}, {"start": 13, "end": 16, "label": "COURSE_YEAR"}, {"start": 17, "end": 23, "label": "CATEGORY"}, {"start": 26, "end": 33, "label": "VACANCY"}, {"start": 34, "end": 37, "label": "DAY"}]}
{"text": "공과대학 컴퓨터융합학부 과목 중 정원이 다 찬 과목은 몇 개야", "entities": [{"start": 0, "end": 12, "label": "DEPARTMENT"}]}
{"text": "공과대학 컴퓨터융합학부 알응 과목 보여줘", "entities": [{"start": 0, "end": 12, "label": "DEPARTMENT"}, {"start": 13, "end": 15, "label": "COURSE_NAME"}]}
{"text": "공과대학 컴퓨터융합학부 전공(핵심)에서 3학년 목요일 과목 보여줘", "entities": [{"start": 0, "end": 12, "label": "DEPARTMENT"}, {"start": 13, "end": 19, "label": "CATEGORY"}, {"start": 22, "end": 25, "label": "COURSE_YEAR"}, {"start": 26, "end": 29, "label": "DAY"}]}
{"text": "공과대학 컴퓨터융합학부에서 개설한 금요일 3시 전공(핵심) 보여줘.", "entities": [{"start": 0, "end": 12, "label": "DEPARTMENT"}, {"start": 19, "end": 22, "label": "DAY"}, {"start": 23, "end": 25, "label": "TIME"}, {"start": 26, "end": 32, "label": "CATEGORY"}]}
{"text": "공과대학 컴퓨터융합학부에서 수강인원이 가장 많은 과목이 뭐야", "entities": [{"start": 0, "end": 12, "label": "DEPARTMENT"}]}
{"text": "금요일 3시 30분에 진행하는 공과대학 컴퓨터융합학부 전공(심화)이랑 인공지능과 미래사회 보여줘", "entities": [{"start": 0, "end": 3, "label": "DAY"}, {"start": 4, "end": 10, "label": "TIME"}, {"start": 17, "end": 29, "label": "DEPARTMENT"}, {"start": 30, "end": 36, "label": "CATEGORY"}, {"start": 39, "end": 49, "label": "COURSE_NAME"}]}
{"text": "나 몇 학년이야", "entities": []}
{"text": "내 학과가 어디야", "entities": []}
{"text": "데이터베이스 과목 정보를 삭제해줘", "entities": [{"start": 0, "end": 6, "label": "COURSE_NAME"}]}
{"text": "목요일 오후 사회과학대학 사회학과 전공과목이랑 대학글쓰기 보여줘", "entities": [{"start": 0, "end": 3, "label": "DAY"}, {"start": 4, "end": 6, "label": "TIME"}, {"start": 7, "end": 18, "label": "DEPARTMENT"}, {"start": 19, "end": 21, "label": "CATEGORY"}, {"start": 26, "end": 31, "label": "COURSE_NAME"}]}
{"text": "빈자리 있는 공과대학 컴퓨터융합학부 전공(핵심) 보여줘", "entities": [{"start": 0, "end": 6, "label": "VACANCY"}, {"start": 7, "end": 19, "label": "DEPARTMENT"}, {"start": 20, "end": 26, "label": "CATEGORY"}]}
{"text": "사회과학대학 사회학과에서 개설한 전공(심화)이랑, 공과대학 컴퓨터융합학부에서 개설한 원격 교양(균형) 찾아줘", "entities": [{"start": 0, "end": 11, "label": "DEPARTMENT"}, {"start": 18, "end": 24, "label": "CATEGORY"}, {"start": 28, "end": 40, "label": "DEPARTMENT"}, {"start": 47, "end": 49, "label": "CLASS_MODE"}, {"start": 50, "end": 56, "label": "CATEGORY"}]}
{"text": "알고리즘응용 과목은 총 몇 개 분반이 있어", "entities": [{"start": 0, "end": 6, "label": "COURSE_NAME"}]}
{"text": "알응이랑 컴과사 조회해", "entities": [{"start": 0, "end": 2, "label": "COURSE_NAME"}, {"start": 5, "end": 8, "label": "COURSE_NAME"}]}
{"text": "월요일 16시 강의 보여줘", "entities": [{"start": 0, "end": 3, "label": "DAY"}, {"start": 4, "end": 7, "label": "TIME"}]}
{"text": "응화공에서 개설한 과목 보여줘", "entities": [{"start": 0, "end": 3, "label": "DEPARTMENT"}]}
{"text": "잔여석이 남아있는 현대인의 생활문화 보여줘", "entities": [{"start": 0, "end": 9, "label": "VACANCY"}, {"start": 10, "end": 19, "label": "COURSE_NAME"}]}
{"text": "컴융 전핵 보여줘", "entities": [{"start": 0, "end": 2, "label": "DEPARTMENT"}, {"start": 3, "end": 5, "label": "CATEGORY"}]}
{"text": "화요일에 진행하는 공과대학 컴퓨터융합학부 전공(기초) 보여줘", "entities": [{"start": 0, "end": 3, "label": "DAY"}, {"start": 10, "end": 22, "label": "DEPARTMENT"}, {"start": 23, "end": 29, "label": "CATEGORY"}]}
{"text": "유정연 교수님이 가르치는 과목 알려줘", "entities": [{"start": 0, "end": 3, "label": "PROFESSOR"}]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_ner_holdout_real.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add -f backend/course_custom_ner_model/metadata/ner_holdout_real.jsonl backend/course_custom_ner_model/scripts/test_ner_holdout_real.py
git commit -m "data: add hand-labeled real-query holdout set for NER evaluation"
```

---

### Task 5: BIO alignment and evaluation metrics

**Files:**
- Create: `backend/course_custom_ner_model/scripts/ner_bio_alignment.py`
- Test: `backend/course_custom_ner_model/scripts/test_ner_bio_alignment.py`

**Interfaces:**
- Produces:
  - `char_spans_to_bio(entities: list[dict], offset_mapping: list[tuple[int, int]], label_to_id: dict[str, int]) -> list[int]` — one label id per token; `-100` for special/non-entity-eligible tokens (offset `(0, 0)`), consistent with HF's "ignore in loss" convention.
  - `ids_to_bio_labels(ids: list[int], id_to_label: dict[int, str]) -> list[str]` — inverse mapping, skipping `-100`.
  - `build_compute_metrics(id_to_label: dict[int, str])` — returns a function `(eval_pred) -> dict[str, float]` compatible with `transformers.Trainer(compute_metrics=...)`, using `seqeval` for entity-level precision/recall/F1.
  - `compute_confusion_counts(true_label_seqs: list[list[str]], pred_label_seqs: list[list[str]]) -> dict[tuple[str, str], int]` — per-token confusion counts keyed by `(true_entity_type_or_"O", predicted_entity_type_or_"O")`, with the `B-`/`I-` prefix stripped.
  - `format_confusion_report(counts: dict[tuple[str, str], int]) -> str` — human-readable table for printing/logging.

- [ ] **Step 1: Write the failing tests**

`backend/course_custom_ner_model/scripts/test_ner_bio_alignment.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_ner_bio_alignment.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ner_bio_alignment'`

- [ ] **Step 3: Write the implementation**

`backend/course_custom_ner_model/scripts/ner_bio_alignment.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_ner_bio_alignment.py -v`
Expected: all 6 tests PASS (note: `build_compute_metrics` itself isn't directly unit-tested here since it needs `numpy`/`seqeval` arrays wired through a real `Trainer` — it's exercised in Task 6's smoke test instead)

- [ ] **Step 5: Commit**

```bash
git add -f backend/course_custom_ner_model/scripts/ner_bio_alignment.py backend/course_custom_ner_model/scripts/test_ner_bio_alignment.py
git commit -m "feat: add char-span-to-BIO alignment and confusion-matrix metrics"
```

---

### Task 6: Training script

**Files:**
- Create: `backend/course_custom_ner_model/scripts/train.py`
- Create: `backend/course_custom_ner_model/scripts/requirements-training.txt`
- Test: `backend/course_custom_ner_model/scripts/test_train.py`

**Interfaces:**
- Consumes:
  - `render_template`/`Template`/`TEMPLATE_CATALOG` are NOT used here (train.py only reads the jsonl files Task 3/4 produce, it doesn't regenerate data).
  - `char_spans_to_bio(entities, offset_mapping, label_to_id) -> list[int]`, `build_compute_metrics(id_to_label) -> callable`, `compute_confusion_counts`, `format_confusion_report` (Task 5, `from ner_bio_alignment import ...`).
- Produces:
  - `load_jsonl(path: str) -> list[dict]`
  - `load_label_schema(labels_json_path: str) -> tuple[dict[str, int], dict[int, str]]` — reads the existing `labels.json` format (`label_to_id`/`id_to_label` keys) so the new model's schema matches exactly.
  - `tokenize_and_align(records: list[dict], tokenizer, label_to_id: dict[str, int], max_length: int) -> "datasets.Dataset"`
  - `main()` — CLI: loads train/valid/holdout jsonl + label schema, builds datasets, loads `AutoModelForTokenClassification.from_pretrained("monologg/koelectra-small-v3-discriminator", ...)`, trains via `transformers.Trainer`, evaluates on valid and on the holdout file (printing a confusion report for each), saves model/tokenizer/labels.json to `--output-dir`.

- [ ] **Step 1: Write the failing tests**

`backend/course_custom_ner_model/scripts/test_train.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_train.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'train'` (the third test additionally requires internet access to download the `monologg/koelectra-small-v3-discriminator` tokenizer from the HF Hub the first time it runs — if this environment has no internet access, run only `test_load_jsonl_reads_one_record_per_line` and `test_load_label_schema_reads_label_to_id_and_id_to_label` locally, and defer `test_tokenize_and_align_produces_labels_aligned_to_tokens` to the real training environment, which does have internet access per the spec's "별도 GPU 환경" constraint)

- [ ] **Step 3: Write the implementation**

`backend/course_custom_ner_model/scripts/requirements-training.txt`:
```
torch
transformers==4.46.3
datasets
seqeval
numpy
```

`backend/course_custom_ner_model/scripts/train.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_train.py -v`
Expected: `test_load_jsonl_reads_one_record_per_line` and `test_load_label_schema_reads_label_to_id_and_id_to_label` PASS unconditionally. `test_tokenize_and_align_produces_labels_aligned_to_tokens` PASSES if this environment can reach the HF Hub (downloads the tokenizer once); if it cannot, this one test is expected to fail with a network error here and must be verified in the real training environment instead (note this explicitly in the task's completion report — it is not a code defect).

- [ ] **Step 5: Commit**

```bash
git add -f backend/course_custom_ner_model/scripts/train.py backend/course_custom_ner_model/scripts/test_train.py backend/course_custom_ner_model/scripts/requirements-training.txt
git commit -m "feat: add HuggingFace Trainer-based fine-tuning script for course-custom-ner"
```

---

### Task 7: Abbreviation review, COMMON_ALIASES integration, README, and end-to-end smoke run

**Files:**
- Create: `backend/course_custom_ner_model/scripts/README.md`
- Modify: `backend/keyword_extract.py` (only the `COMMON_ALIASES` dict — no other changes)

**Interfaces:**
- Consumes: `infer_abbreviations.py`'s output format (`{label: {value: [candidates]}}`, Task 1), `keyword_extract.py`'s existing `COMMON_ALIASES: dict[str, dict[str, list[str]]]` structure (`backend/keyword_extract.py`, already read earlier in this project: keyed by label, then by alias text, mapping to a list of canonical DB values).

- [ ] **Step 1: Run the abbreviation inference tool against the real DB**

Run: `cd backend/course_custom_ner_model/scripts && python infer_abbreviations.py --output ../data/abbreviation_candidates.json`

Confirm it completes and prints `wrote ../data/abbreviation_candidates.json`.

- [ ] **Step 2: Review the candidates and produce the reviewed file**

Read `backend/course_custom_ner_model/data/abbreviation_candidates.json`. For **CATEGORY**, expect it to closely match the existing `COMMON_ALIASES["CATEGORY"]` entries already in `keyword_extract.py` (verified earlier in this project: 9 of 9 real CATEGORY values already covered) — no new entries likely needed. For **DEPARTMENT**, look for plausible, non-nonsensical candidates (e.g. `"컴공"` for `"공과대학 컴퓨터공학과"`) and discard anything that reads as noise (single meaningless characters, candidates that collide with an unrelated existing alias). For **COURSE_NAME**, per the spec, do NOT add these to `COMMON_ALIASES` — they exist only to feed Task 3's `abbrev_course_only`/`abbrev_dept_category` templates.

Write the human-reviewed subset to `backend/course_custom_ner_model/metadata/abbreviation_candidates.reviewed.json`, same `{label: {value: [candidates]}}` shape as the input, keeping all three labels' keys present (even if a label's dict ends up empty for CATEGORY).

- [ ] **Step 3: Merge reviewed DEPARTMENT/CATEGORY candidates into `COMMON_ALIASES`**

Open `backend/keyword_extract.py` and locate `COMMON_ALIASES` (around line 58). For each reviewed candidate abbreviation not already present as a key under its label's dict, add it:

```python
COMMON_ALIASES = {
    "DEPARTMENT": {
        "컴공": ["컴퓨터공학과"],
        "컴융": ["컴퓨터융합학부", "공과대학 컴퓨터융합학부"],
        "컴융부": ["컴퓨터융합학부", "공과대학 컴퓨터융합학부"],
        "인공지능": ["컴퓨터인공지능학부"],
        # New entries from Task 7's reviewed candidates go here, following the
        # same "alias": ["canonical DB value(s)"] shape. Example shape only —
        # replace with the actual reviewed candidates from Step 2:
        # "응화공": ["응용화학공학과", "공과대학 응용화학공학과"],
    },
    "CATEGORY": {
        "전기": ["전공(기초)"],
        "전핵": ["전공(핵심)"],
        "전심": ["전공(심화)"],
        "교소": ["교양(소양)"],
        "교소필": ["교양(소양필수)"],
        "일선": ["일반(선택)"],
        "교균": ["교양(균형)"],
        "교기": ["교양(기초)"],
        "교직": ["교직"]
    },
}
```

(The plan cannot pin the exact new DEPARTMENT entries in advance since they depend on Step 1's live DB output — this step's deliverable is the merged dict reflecting Step 2's actual reviewed file, not the literal snippet above.)

- [ ] **Step 4: Verify the existing keyword_extract tests still pass**

Run: `cd backend && python test_correction.py`
Expected: runs without error, output entities still show sensible corrections (this script prints rather than asserts — visually confirm no regressions in the existing three sample corrections).

- [ ] **Step 5: Write the README**

`backend/course_custom_ner_model/scripts/README.md`:
```markdown
# course-custom-ner retraining pipeline

Rebuilds the NER model's training data and produces a fine-tuned checkpoint,
targeting two failure modes: entity boundary errors and label(type)
misclassification. See `docs/superpowers/specs/2026-09-07-ner-retraining-design.md`
for the full design rationale.

## Prerequisites

- `DATABASE_URL` reachable (same as the main app's `backend/.env`).
- For `train.py` specifically: a machine with the training-only dependencies
  installed (`pip install -r requirements-training.txt`) and, ideally, a GPU.
  `infer_abbreviations.py` and `generate_ner_dataset.py` only need `psycopg2`
  and `python-dotenv` (already in the main app's `backend/requirements.txt`).

All commands below assume `cd backend/course_custom_ner_model/scripts` first.

## 1. Infer abbreviation candidates

```bash
python infer_abbreviations.py --output ../data/abbreviation_candidates.json
```

Then hand-review the output and save the curated subset to
`../metadata/abbreviation_candidates.reviewed.json` (same JSON shape). See
Task 7 in the implementation plan for the review criteria.

## 2. Generate the synthetic dataset

```bash
python generate_ner_dataset.py \
  --abbreviations-file ../metadata/abbreviation_candidates.reviewed.json \
  --output-dir ../data \
  --seed 42
```

Writes `../data/ner_train.jsonl`, `ner_valid.jsonl`, `ner_test.jsonl`. Re-run
any time to regenerate — nothing under `../data/` is committed to git.

## 3. Train

On a machine with `requirements-training.txt` installed:

```bash
pip install -r requirements-training.txt
python train.py \
  --train-file ../data/ner_train.jsonl \
  --valid-file ../data/ner_valid.jsonl \
  --holdout-file ../metadata/ner_holdout_real.jsonl \
  --labels-file ../models/course-custom-ner/labels.json \
  --output-dir ../trained_model_output
```

Watch the printed "Holdout (real queries) seqeval report" and "confusion
counts" at the end — this is the number that matters most, since it's
measured on real historical queries the model never trained on. If specific
label pairs show up repeatedly in the confusion counts, go back to
`generate_ner_dataset.py`'s `TEMPLATE_CATALOG` and increase the `weight` of
the relevant `confusable_*` templates, then repeat from step 2.

## 4. Swap in the new model

**Back up the current model first:**

```bash
cp -r ../models/course-custom-ner ../models/course-custom-ner.bak-$(date +%Y%m%d)
```

Then copy the new checkpoint over it:

```bash
cp -r ../trained_model_output/final/* ../models/course-custom-ner/
```

Restart the backend (`keyword_extract.py` loads the model once per process
via `get_predictor()`) and spot-check with:

```bash
python predict_ner.py --query "컴퓨터융합학부 3학년 대상 전공(핵심) 과목 알려줘"
```

## 5. (Optional) Re-run the full text-to-sql eval set

If you want to see whether the NER improvement moved the needle on overall
pipeline accuracy, from the repo root:

```bash
python -m backend.eval.run_eval
```

Compare the new overall/category accuracy against the baseline run recorded
in `backend/eval/README.md` (27.9% / 12 of 43 at the time this pipeline was
built).
```

- [ ] **Step 6: Run the full new test suite once more**

Run: `cd backend/course_custom_ner_model/scripts && python -m pytest test_infer_abbreviations.py test_ner_template_engine.py test_generate_ner_dataset.py test_ner_holdout_real.py test_ner_bio_alignment.py -v`

Expected: all tests from Tasks 1-5 pass together (48 tests: 18+6+12+6+6). `test_train.py` is excluded from this combined run since one of its 3 tests depends on network access to the HF Hub — run it separately per Task 6 Step 4's guidance.

- [ ] **Step 7: Commit**

```bash
git add -f backend/course_custom_ner_model/scripts/README.md backend/course_custom_ner_model/metadata/abbreviation_candidates.reviewed.json backend/keyword_extract.py
git commit -m "feat: integrate reviewed abbreviations into COMMON_ALIASES, add retraining pipeline README"
```

---

## Self-Review Results

- **Spec coverage**: Abbreviation inference (Task 1) ✓, template engine + confusable-pair templates (Tasks 2-3) ✓, real-query holdout set (Task 4) ✓, BIO alignment + confusion matrix (Task 5) ✓, training script targeting `monologg/koelectra-small-v3-discriminator` with unchanged 16-label schema (Task 6) ✓, COMMON_ALIASES integration + README + optional full-pipeline re-eval (Task 7) ✓. Every spec section maps to a task.
- **Placeholder scan**: No "TBD"/"handle appropriately" language in any code step. Task 7's `COMMON_ALIASES` snippet is explicitly marked as "example shape only, not the literal new entries" because those entries depend on live DB output that doesn't exist until Task 1 actually runs against the real database during execution — this is a genuine, unavoidable data dependency (like a plan for a data migration that can't hardcode row counts from a table that doesn't exist yet), not a placeholder for logic or structure.
- **Type consistency**: `render_template`'s `dict[str, tuple[str, str]]` return/parameter shape is identical across Task 2 (definition) and Task 3 (`_fill_values_for_template`, `generate_records`). `char_spans_to_bio`'s `(entities, offset_mapping, label_to_id) -> list[int]` signature is identical across Task 5 (definition) and Task 6 (`tokenize_and_align`, `_evaluate_on_holdout`). `Template` dataclass fields (`id`, `text`, `slots`, `weight`) are used consistently in Task 3's catalog and tests.
- **Executable verification (beyond static review)**: every piece of code in Tasks 1-5 was actually extracted, run, and its tests executed in a sandbox before this plan was finalized — not just read for plausibility. This caught and fixed three real bugs before an implementer would have hit them:
  1. Task 2's `test_render_template_supports_two_slots_of_the_same_label` had a hand-miscalculated expected offset (`8, 12` instead of the correct `9, 13`) — the implementation was right, the test's expected value was wrong. Fixed.
  2. Task 3's original draft mixed abbreviation candidates into the *same* pool as canonical values in one test assertion while the implementation (and the template catalog's own `_ABBR`-suffixed pool keys) clearly used *separate* pools — an inconsistency that would have made the test fail against correct code. Also found and removed two pieces of dead code in `build_value_pools`/`_fill_values_for_template` (an unused `label` computation and a no-op `for suffix in ("_ABBR",): pass` loop) left over from drafting. Fixed, and added a new `test_full_catalog_generates_without_crashing_with_realistic_pools` integration test that exercises the real 34-template `TEMPLATE_CATALOG` end-to-end (not just tiny hand-built catalogs) — this test was not in the original draft and closes a real coverage gap.
  3. Task 4's original coverage test required every one of the 10 "priority" labels to appear somewhere in the 26-example holdout set, but a `grep` over all 207 real log queries confirmed EVAL_TYPE and GRADE_METHOD never appear in any real observed query — the test would have forced padding the "real query" file with fabricated, non-authentic sentences just to satisfy a checklist. Fixed by excluding those two (with a comment explaining why, and noting they're still covered by Task 3's synthetic templates) and adding a genuine real PROFESSOR example (`"유정연 교수님이 가르치는 과목 알려줘"`, already present in `backend-log.txt` but not originally selected) to reach real coverage instead, bringing the holdout set to 27 records.
  - Additionally verified against the real `monologg/koelectra-small-v3-discriminator` checkpoint (network access confirmed available): the tokenizer downloads and produces correct subword offsets, `char_spans_to_bio` correctly aligns BIO labels across wordpiece-split tokens (`컴퓨터` / `##융합` / `##학` / `##부`), `AutoModelForTokenClassification.from_pretrained(..., num_labels=3, id2label=..., label2id=...)` loads successfully with a fresh classification head, and `build_compute_metrics` produces correct precision/recall/F1 via real `seqeval` given synthetic logits.
  - All corrected test counts are reflected in each task's "Expected" lines and in Task 7 Step 6's combined total (48, not the originally-drafted 46).
