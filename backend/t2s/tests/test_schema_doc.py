from backend.t2s.schema_doc import build_mschema, load_column_docs

DOCS = {
    "tables": [
        {"name": "t", "description": "설명", "columns": [
            {"name": "a", "type": "VARCHAR", "description": "작은 열", "values": "auto"},
            {"name": "b", "type": "VARCHAR", "description": "큰 열", "values": "auto"},
            {"name": "c", "type": "INTEGER", "description": "비공개", "values": "none"},
        ]},
    ],
    "foreign_keys": ["t.a → u.a"],
}


def fake_fetch(sql, params=None):
    if "COUNT(DISTINCT a)" in sql:
        return [{"n": 2}]
    if "COUNT(DISTINCT b)" in sql:
        return [{"n": 30}]
    if "DISTINCT a" in sql:
        return [{"v": "x"}, {"v": "y"}]
    if "b AS v" in sql:
        return [{"v": "p"}, {"v": "q"}, {"v": "r"}]
    raise AssertionError(sql)


def test_build_mschema_lists_small_columns_fully_and_samples_large_ones():
    text = build_mschema(DOCS, fake_fetch)

    assert text.splitlines()[0] == "# Table: t (설명)"
    assert "(a: VARCHAR, 작은 열, Values: ['x', 'y'])," in text
    assert "(b: VARCHAR, 큰 열, Examples: ['p', 'q', 'r'])," in text
    assert "(c: INTEGER, 비공개)" in text
    assert text.rstrip().endswith("【Foreign keys】\nt.a → u.a")


def test_shipped_yaml_covers_every_v_course_info_column():
    from backend.t2s.postprocess import STANDARD_COLUMNS

    docs = load_column_docs()
    v = next(t for t in docs["tables"] if t["name"] == "v_course_info")

    assert tuple(c["name"] for c in v["columns"]) == STANDARD_COLUMNS
