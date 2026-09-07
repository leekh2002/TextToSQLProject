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
