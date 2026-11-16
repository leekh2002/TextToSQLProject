from backend.eval.validate_golden import EXPANSION_CAP, check_cases, like_keywords


def case(**overrides):
    base = {
        "id": "c1", "category": "course_filter", "query": "q1", "grading": "execution",
        "reference_sql": "SELECT 1", "expects_error": False, "student_id": None,
    }
    base.update(overrides)
    return base


def identity(sql):
    return sql


def rows(n):
    return lambda sql: [{"a": i} for i in range(n)]


def test_clean_case_has_no_problems():
    assert check_cases([case()], run=rows(3), expand=identity) == ([], [])


def test_duplicate_ids_and_queries_are_problems():
    problems, _ = check_cases([case(), case(query="q2"), case(id="c3")], run=rows(1), expand=identity)

    assert any("id 중복" in p and "c1" in p for p in problems)
    assert any("질의 중복" in p and "q1" in p for p in problems)


def test_empty_reference_requires_empty_gold_flag():
    problems, _ = check_cases([case()], run=rows(0), expand=identity)
    assert any("0행" in p for p in problems)

    assert check_cases([case(empty_gold=True)], run=rows(0), expand=identity) == ([], [])

    problems, _ = check_cases([case(empty_gold=True)], run=rows(2), expand=identity)
    assert any("empty_gold" in p for p in problems)


def test_reference_sql_is_expanded_before_running():
    seen = []

    def run(sql):
        seen.append(sql)
        return [{"a": 1}]

    check_cases([case()], run=run, expand=lambda sql: sql + " X")

    assert seen == ["SELECT 1 X"]


def test_failing_reference_sql_is_a_problem():
    def run(sql):
        raise RuntimeError("syntax error")

    problems, _ = check_cases([case()], run=run, expand=identity)

    assert any("syntax error" in p for p in problems)


def test_gold_values_format_is_checked():
    good = case(gold_values=[{"column": "dept_name", "value": "공과대학 컴퓨터융합학부"}])
    bad = case(id="c2", query="q2", gold_values=[{"column": "dept_name"}])

    problems, _ = check_cases([good, bad], run=rows(1), expand=identity)

    assert len(problems) == 1 and "c2" in problems[0]


def test_student_cases_must_use_the_known_student():
    problems, _ = check_cases([case(student_id="209999999")], run=rows(1), expand=identity)

    assert any("202102671" in p for p in problems)


def test_structural_cases_are_not_executed():
    def run(sql):
        raise AssertionError("must not run")

    assert check_cases([case(grading="structural", reference_sql=None)], run=run, expand=identity) == ([], [])


def test_more_rows_than_the_row_cap_is_a_warning(monkeypatch):
    monkeypatch.delenv("T2S_ROW_CAP", raising=False)

    problems, warnings = check_cases([case()], run=rows(51), expand=identity)
    assert problems == []
    assert len(warnings) == 1 and "51" in warnings[0]

    assert check_cases([case()], run=rows(50), expand=identity) == ([], [])


def test_hitting_the_expansion_cap_is_a_warning(monkeypatch):
    monkeypatch.delenv("T2S_ROW_CAP", raising=False)

    problems, warnings = check_cases([case()], run=rows(EXPANSION_CAP), expand=identity)

    assert problems == []
    assert any(str(EXPANSION_CAP) in w and "확장" in w for w in warnings)


# --- gold_values vs LIKE keywords ---

def fake_distinct(values_by_pattern):
    seen = []

    def distinct(column, pattern):
        seen.append((column, pattern))
        return values_by_pattern[(column, pattern)]

    distinct.seen = seen
    return distinct


def like_case(gold, sql="SELECT 1 FROM v_course_info WHERE dept_name LIKE '%컴퓨터융합학부%' AND subject_name LIKE '%자료구조%'", **overrides):
    return case(reference_sql=sql, gold_values=gold, **overrides)


def test_gold_value_for_unique_like_keyword_must_be_that_db_value():
    distinct = fake_distinct({
        ("dept_name", "%컴퓨터융합학부%"): ["공과대학 컴퓨터융합학부"],
        ("subject_name", "%자료구조%"): ["자료구조", "자료구조및실습"],
    })
    good = like_case([{"column": "dept_name", "value": "공과대학 컴퓨터융합학부"}])
    assert check_cases([good], run=rows(1), expand=identity, distinct_like=distinct) == ([], [])
    assert ("dept_name", "%컴퓨터융합학부%") in distinct.seen

    wrong = like_case([{"column": "dept_name", "value": "컴퓨터융합학부"}])
    problems, _ = check_cases([wrong], run=rows(1), expand=identity, distinct_like=distinct)
    assert len(problems) == 1 and "c1" in problems[0] and "공과대학 컴퓨터융합학부" in problems[0]


def test_gold_value_for_multi_match_like_keyword_is_an_error():
    distinct = fake_distinct({
        ("dept_name", "%컴퓨터융합학부%"): ["공과대학 컴퓨터융합학부"],
        ("subject_name", "%자료구조%"): ["자료구조", "자료구조및실습"],
    })
    bad = like_case([{"column": "subject_name", "value": "자료구조"}])

    problems, _ = check_cases([bad], run=rows(1), expand=identity, distinct_like=distinct)

    assert len(problems) == 1 and "subject_name" in problems[0] and "2" in problems[0]


def test_like_check_ignores_not_like_equality_and_unfiltered_gold_columns():
    def distinct(column, pattern):
        raise AssertionError(f"must not look up {column} {pattern}")

    sql = "SELECT 1 FROM v_course_info WHERE subject_name NOT LIKE '%실습%' AND day_of_week = '월'"
    gold = [{"column": "subject_name", "value": "자료구조"}, {"column": "day_of_week", "value": "월"}]

    assert check_cases([like_case(gold, sql=sql)], run=rows(1), expand=identity, distinct_like=distinct) == ([], [])


def test_like_keywords_are_parsed_with_table_qualifiers():
    assert like_keywords("SELECT * FROM v_course_info AS v WHERE v.dept_name LIKE '%경상대학 경제학과%' "
                         "OR v.category like '%교양(소양필수)%' AND x NOT LIKE '%y%' AND credit_hours LIKE '3/%'") == {
        "dept_name": ["%경상대학 경제학과%"],
        "category": ["%교양(소양필수)%"],
    }
