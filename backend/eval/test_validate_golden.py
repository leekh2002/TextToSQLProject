from backend.eval.validate_golden import MAX_ROWS, check_cases


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


def test_too_many_rows_is_a_warning():
    problems, warnings = check_cases([case()], run=rows(MAX_ROWS + 1), expand=identity)

    assert problems == []
    assert any(str(MAX_ROWS + 1) in w for w in warnings)


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
