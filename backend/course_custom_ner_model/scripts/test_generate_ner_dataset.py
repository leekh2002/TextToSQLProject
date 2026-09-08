import random

from generate_ner_dataset import (
    DAY_VALUES,
    TEMPLATE_CATALOG,
    Template,
    build_value_pools,
    generate_course_year_values,
    generate_credit_values,
    generate_records,
    generate_section_values,
    generate_time_values,
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


def test_split_by_template_guarantees_every_label_has_train_support():
    templates_by_id = {
        "common_a": ["DEPARTMENT"],
        "common_b": ["DEPARTMENT"],
        "common_c": ["CATEGORY"],
        "common_d": ["CATEGORY"],
        "rare_only": ["COURSE_YEAR"],
    }
    records = []
    for tid, labels in templates_by_id.items():
        for _ in range(3):
            records.append(
                {
                    "template_id": tid,
                    "text": "x",
                    "entities": [{"start": 0, "end": 1, "label": label} for label in labels],
                }
            )
    train, valid, test = split_by_template(records, valid_ratio=0.2, test_ratio=0.2, rng=random.Random(4))
    train_labels = {e["label"] for r in train for e in r["entities"]}
    assert "COURSE_YEAR" in train_labels


def test_day_values_include_yoil_suffixed_forms():
    assert any(v.endswith("요일") for v in DAY_VALUES)


def test_generate_time_values_can_produce_24h_and_meridiem_forms():
    values = generate_time_values(random.Random(1), 200)
    assert any(v in ("오전", "오후") for v in values)

    def _is_afternoon_hour_form(v: str) -> bool:
        if v in ("오전", "오후") or "시" not in v:
            return False
        hour_part = v.split("시")[0].strip()
        return hour_part.isdigit() and int(hour_part) >= 13

    assert any(_is_afternoon_hour_form(v) for v in values)


ATTACHABLE_PARTICLES = ("에서", "에", "은", "는", "의", "이랑", "부터", "까지")

# Particles the real queries attach to entities ("학부에서", "화요일에") that
# the catalog never produced — it only ever attached 이랑/부터/까지.
LOCATIVE_PARTICLES = ("에서", "에", "은", "는", "의")


def _realistic_pools():
    db_values = {
        "DEPARTMENT": ["공과대학 컴퓨터융합학부", "경상대학 경제학과", "사회과학대학 사회학과"],
        "CATEGORY": ["전공(핵심)", "전공(기초)", "일반선택", "교양(균형)"],
        "COURSE_NAME": ["데이터베이스", "자료구조", "인공지능과 미래사회"],
        "PROFESSOR": ["유정연", "이규철"],
        "CLASS_MODE": ["실시간", "콘텐츠", "원격"],
        "EVAL_TYPE": ["GRADE", "PASS"],
        "GRADE_METHOD": ["상대평가", "절대평가"],
    }
    abbreviations = {
        "DEPARTMENT": {"공과대학 컴퓨터융합학부": ["컴융"]},
        "CATEGORY": {"전공(핵심)": ["전핵"]},
        "COURSE_NAME": {"데이터베이스": ["디비"]},
    }
    rng = random.Random(42)
    return build_value_pools(db_values, abbreviations, rng)


def _corpus():
    return generate_records(TEMPLATE_CATALOG, _realistic_pools(), random.Random(7))


def test_every_label_appears_in_at_least_three_templates():
    # A label carried by fewer than three templates cannot be present in all
    # of train, valid and test at once, because splitting happens per template.
    counts: dict[str, int] = {}
    for template in TEMPLATE_CATALOG:
        for pool_key in set(template.slots.values()):
            label = pool_key[: -len("_ABBR")] if pool_key.endswith("_ABBR") else pool_key
            counts[label] = counts.get(label, 0) + 1

    lacking = {label: n for label, n in counts.items() if n < 3}
    assert not lacking, lacking


def test_generated_records_attach_locative_particles_directly_after_an_entity():
    hits = 0
    for record in _corpus():
        for entity in record["entities"]:
            if record["text"][entity["end"] :].startswith(LOCATIVE_PARTICLES):
                hits += 1
    assert hits >= 10, hits


def test_generated_records_glue_a_multi_syllable_word_onto_an_entity():
    # "2학년대상 ... 전공과목" — the model merged the whole run into one span
    # because it had never seen an entity butted up against a real word.
    hits = 0
    for record in _corpus():
        for entity in record["entities"]:
            run = record["text"][entity["end"] :].split(" ")[0]
            if len(run) >= 2 and not run.startswith(ATTACHABLE_PARTICLES):
                hits += 1
    assert hits >= 10, hits


def test_generated_records_include_sentences_with_no_entity_at_all():
    empty = [r for r in _corpus() if not r["entities"]]
    assert len(empty) >= 5, len(empty)


def test_generated_entity_spans_never_swallow_surrounding_template_text():
    pools = _realistic_pools()
    for record in generate_records(TEMPLATE_CATALOG, pools, random.Random(3)):
        for entity in record["entities"]:
            span = record["text"][entity["start"] : entity["end"]]
            label = entity["label"]
            allowed = set(pools.get(label, [])) | set(pools.get(f"{label}_ABBR", []))
            assert span in allowed, (record["template_id"], record["text"], span, label)


def test_generate_records_scale_multiplies_the_record_count():
    catalog = [Template(id="t", text="{DAY} 수업", slots={"DAY": "DAY"}, weight=4)]
    pools = {"DAY": ["월"]}
    assert len(generate_records(catalog, pools, random.Random(0), scale=1)) == 4
    assert len(generate_records(catalog, pools, random.Random(0), scale=3)) == 12


def test_split_by_template_puts_every_label_in_all_three_splits():
    records = _corpus()
    train, valid, test = split_by_template(records, valid_ratio=0.15, test_ratio=0.15, rng=random.Random(11))

    def labels(rs):
        return {e["label"] for r in rs for e in r["entities"]}

    all_labels = labels(records)
    assert labels(train) == all_labels, all_labels - labels(train)
    assert labels(valid) == all_labels, all_labels - labels(valid)
    assert labels(test) == all_labels, all_labels - labels(test)
