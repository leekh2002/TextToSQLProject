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


DAY_VALUES = [
    "월", "화", "수", "목", "금", "토", "일",
    "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
]
VACANCY_PHRASES = ["빈자리가 있는", "빈자리 있는", "잔여석이 남아있는", "자리가 남은"]


def generate_time_values(rng: random.Random, count: int) -> list[str]:
    values = []
    for _ in range(count):
        style = rng.choice(["hour_12", "hour_24", "hour_minute", "24h_colon", "meridiem"])
        if style == "meridiem":
            values.append(rng.choice(["오전", "오후"]))
            continue
        hour = rng.randint(1, 12)
        if style == "hour_12":
            values.append(f"{hour}시")
        elif style == "hour_24":
            values.append(f"{rng.randint(13, 24)}시")
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
    # --- Particles attached straight onto an entity -------------------------
    # Real queries say "학부에서", "화요일에", "교수님의". The catalog only ever
    # attached 이랑/부터/까지, so the model learned to swallow 에/에서 into the
    # span (or to tag the leftover 서/에 as its own entity).
    Template(
        "particle_dept_eseo_category",
        "{DEPARTMENT}에서 개설한 {CATEGORY} 보여줘",
        {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"},
        weight=25,
    ),
    Template(
        "particle_dept_eseo_day_time",
        "{DEPARTMENT}에서 개설한 {DAY} {TIME} 수업 알려줘",
        {"DEPARTMENT": "DEPARTMENT", "DAY": "DAY", "TIME": "TIME"},
        weight=20,
    ),
    Template(
        "particle_day_e_dept_category",
        "{DAY}에 진행하는 {DEPARTMENT} {CATEGORY} 보여줘",
        {"DAY": "DAY", "DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"},
        weight=20,
    ),
    Template(
        "particle_dept_eseo_credit",
        "{DEPARTMENT}에서 {CREDIT} 과목 알려줘",
        {"DEPARTMENT": "DEPARTMENT", "CREDIT": "CREDIT"},
        weight=12,
    ),
    Template(
        "particle_professor_eui_category",
        "{PROFESSOR} 교수님의 {CATEGORY} 알려줘",
        {"PROFESSOR": "PROFESSOR", "CATEGORY": "CATEGORY"},
        weight=12,
    ),
    Template(
        "particle_dept_eseo_professor",
        "{DEPARTMENT}에서 {PROFESSOR} 교수님 수업 찾아줘",
        {"DEPARTMENT": "DEPARTMENT", "PROFESSOR": "PROFESSOR"},
        weight=12,
    ),
    Template(
        "particle_room_eseo_category",
        "{ROOM}에서 하는 {CATEGORY} 알려줘",
        {"ROOM": "ROOM", "CATEGORY": "CATEGORY"},
        weight=8,
    ),
    Template(
        "particle_class_mode_eun",
        "{CLASS_MODE} 수업은 뭐가 있어",
        {"CLASS_MODE": "CLASS_MODE"},
        weight=12,
    ),
    Template(
        "particle_dept_eseo_eval_type",
        "{DEPARTMENT}에서 {EVAL_TYPE} 방식 과목 보여줘",
        {"DEPARTMENT": "DEPARTMENT", "EVAL_TYPE": "EVAL_TYPE"},
        weight=10,
    ),
    Template(
        "particle_grade_method_neun",
        "{GRADE_METHOD}는 어떤 과목이 있어",
        {"GRADE_METHOD": "GRADE_METHOD"},
        weight=10,
    ),
    Template(
        "particle_course_eun_question",
        "{COURSE_NAME}은 언제 하는 수업이야",
        {"COURSE_NAME": "COURSE_NAME"},
        weight=12,
    ),
    # --- Entities butted up against a real word, with no space -------------
    # "2학년대상 ... 전공과목" made the model merge the whole run into one span.
    Template(
        "glued_year_daesang",
        "{COURSE_YEAR}대상 {DEPARTMENT} {CATEGORY}과목 찾아줘",
        {"COURSE_YEAR": "COURSE_YEAR", "DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"},
        weight=20,
    ),
    Template(
        "glued_category_gwamok",
        "{DEPARTMENT} {CATEGORY}과목 보여줘",
        {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"},
        weight=18,
    ),
    Template(
        "glued_time_gangui",
        "{DAY} {TIME}강의 보여줘",
        {"DAY": "DAY", "TIME": "TIME"},
        weight=15,
    ),
    Template(
        "glued_dept_gaeseol",
        "{DEPARTMENT}개설 {CATEGORY} 알려줘",
        {"DEPARTMENT": "DEPARTMENT", "CATEGORY": "CATEGORY"},
        weight=12,
    ),
    Template(
        "glued_capacity_isang",
        "정원이 {CAPACITY} 이상인 {DEPARTMENT} 과목 보여줘",
        {"CAPACITY": "CAPACITY", "DEPARTMENT": "DEPARTMENT"},
        weight=8,
    ),
    Template(
        "glued_enrolled_category",
        "{ENROLLED} 신청한 {CATEGORY} 보여줘",
        {"ENROLLED": "ENROLLED", "CATEGORY": "CATEGORY"},
        weight=8,
    ),
    Template(
        "confusable_capacity_enrolled_2",
        "{DEPARTMENT} 과목 중 정원 {CAPACITY}에 {ENROLLED} 찬 거 알려줘",
        {"DEPARTMENT": "DEPARTMENT", "CAPACITY": "CAPACITY", "ENROLLED": "ENROLLED"},
        weight=8,
    ),
    Template(
        "confusable_credit_section",
        "{CREDIT} {SECTION} 과목 알려줘",
        {"CREDIT": "CREDIT", "SECTION": "SECTION"},
        weight=8,
    ),
    # --- Sentences with no entity at all -----------------------------------
    # Every synthetic sentence used to contain at least one entity, so the
    # model had never seen a query it should leave alone and tagged pronouns
    # and adverbs ('나', '내', '몇') instead.
    Template("no_entity_my_year", "나 몇 학년이야", {}, weight=8),
    Template("no_entity_my_dept", "내 학과가 어디야", {}, weight=8),
    Template("no_entity_total_count", "총 몇 개 과목이 있어", {}, weight=8),
    Template("no_entity_help", "뭘 할 수 있어?", {}, weight=6),
    Template("no_entity_greeting", "안녕 반가워", {}, weight=6),
    Template("no_entity_enroll_when", "수강신청은 언제야", {}, weight=6),
    Template("no_entity_thanks", "고마워 도움이 됐어", {}, weight=5),
    Template("no_entity_reset", "방금 조건 다 지워줘", {}, weight=5),
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

    if "CATEGORY" in pools and pools["CATEGORY"]:
        for generic in ("전공", "교양"):
            if generic not in pools["CATEGORY"]:
                pools["CATEGORY"] = pools["CATEGORY"] + [generic]

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
    scale: int = 1,
) -> list[dict]:
    records: list[dict] = []
    for template in template_catalog:
        for _ in range(template.weight * scale):
            values = _fill_values_for_template(template, value_pools, rng)
            rendered = render_template(template.text, values)
            records.append({"template_id": template.id, "text": rendered["text"], "entities": rendered["entities"]})
    return records


def _labels_covered_by_records(records: list[dict]) -> set[str]:
    return {entity["label"] for record in records for entity in record["entities"]}


def _leaves_train_support(
    template_id: str,
    labels_by_template: dict[str, set[str]],
    templates_by_label: dict[str, list[str]],
    assignment: dict[str, str],
) -> bool:
    """True if moving this template out of train still leaves every one of its
    labels with another train-bound template."""
    for label in labels_by_template[template_id]:
        others = [
            other
            for other in templates_by_label[label]
            if other != template_id and other not in assignment
        ]
        if not others:
            return False
    return True


def split_by_template(
    records: list[dict],
    valid_ratio: float,
    test_ratio: float,
    rng: random.Random,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split per template, never per record.

    Sharing a template between train and eval would let the model memorise the
    template and inflate the scores, so a template lands wholly in one split.
    The cost is label coverage: with few templates an entire label can miss a
    split, which is what left ner_valid.jsonl covering 7 of 16 labels. So
    templates are picked for valid and test by label first — rarest label
    first, since those have the fewest templates to spare — and only then
    topped up to the requested ratios.
    """
    template_ids = sorted({record["template_id"] for record in records})

    records_by_template: dict[str, list[dict]] = {}
    for record in records:
        records_by_template.setdefault(record["template_id"], []).append(record)

    labels_by_template = {
        tid: _labels_covered_by_records(rs) for tid, rs in records_by_template.items()
    }
    templates_by_label: dict[str, list[str]] = {}
    for tid, labels in labels_by_template.items():
        for label in labels:
            templates_by_label.setdefault(label, []).append(tid)

    total = len(template_ids)
    targets = {
        "test": max(1, int(total * test_ratio)) if total > 1 else 0,
        "valid": max(1, int(total * valid_ratio)) if total > 1 else 0,
    }

    assignment: dict[str, str] = {}
    sizes = {"test": 0, "valid": 0}
    covered: dict[str, set[str]] = {"test": set(), "valid": set()}

    # Coverage wins over the ratio: a split that misses a label cannot measure
    # it at all, whereas being a few templates over 15% only shifts the sizes.
    for label in sorted(templates_by_label, key=lambda l: (len(templates_by_label[l]), l)):
        for split in ("test", "valid"):
            if label in covered[split]:
                continue
            spare = [
                tid
                for tid in templates_by_label[label]
                if tid not in assignment
                and _leaves_train_support(tid, labels_by_template, templates_by_label, assignment)
            ]
            if not spare:
                continue
            chosen = spare[rng.randrange(len(spare))]
            assignment[chosen] = split
            sizes[split] += 1
            covered[split] |= labels_by_template[chosen]

    leftover = [tid for tid in template_ids if tid not in assignment]
    rng.shuffle(leftover)
    for split in ("test", "valid"):
        for tid in leftover:
            if sizes[split] >= targets[split]:
                break
            if tid in assignment:
                continue
            if not _leaves_train_support(tid, labels_by_template, templates_by_label, assignment):
                continue
            assignment[tid] = split
            sizes[split] += 1

    train = [r for r in records if assignment.get(r["template_id"], "train") == "train"]
    valid = [r for r in records if assignment.get(r["template_id"]) == "valid"]
    test = [r for r in records if assignment.get(r["template_id"]) == "test"]
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
    parser.add_argument(
        "--scale",
        type=int,
        default=1,
        help="multiply every template's record count; the catalog weights are per-scale-unit",
    )
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
    records = generate_records(TEMPLATE_CATALOG, value_pools, rng, scale=args.scale)
    train, valid, test = split_by_template(records, args.valid_ratio, args.test_ratio, rng)

    output_dir = Path(args.output_dir)
    _write_jsonl(train, output_dir / "ner_train.jsonl")
    _write_jsonl(valid, output_dir / "ner_valid.jsonl")
    _write_jsonl(test, output_dir / "ner_test.jsonl")
    print(f"train={len(train)} valid={len(valid)} test={len(test)} -> {output_dir}")


if __name__ == "__main__":
    main()
