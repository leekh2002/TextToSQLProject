from backend.t2s.execute import CandidateOutcome
from backend.t2s.vote import Decision, decide, result_signature


def out(i, rows=None, error=None, rejected=False):
    return CandidateOutcome(index=i, raw="x", rows=rows, error=error, rejected=rejected)


A = [{"subject_code": "A", "n": 1}]
B = [{"subject_code": "B", "n": 1}]


def test_signature_ignores_row_and_key_order():
    assert result_signature([{"a": 1, "b": 2}, {"a": 3, "b": 4}]) == result_signature([{"b": 4, "a": 3}, {"b": 2, "a": 1}])


def test_majority_group_wins_and_picks_lowest_index():
    assert decide([out(0, B), out(1, A), out(2, A), out(3, error="x")], 5) == Decision("answer", 1)


def test_tie_prefers_group_containing_greedy_candidate():
    assert decide([out(0, A), out(1, B)], 2) == Decision("answer", 0)


def test_non_empty_beats_larger_empty_group():
    assert decide([out(0, []), out(1, []), out(2, A)], 3) == Decision("answer", 2)


def test_all_empty_and_no_success():
    assert decide([out(0, []), out(1, error="e")], 2) == Decision("empty", 0)
    assert decide([out(0, error="e"), out(1)], 2) == Decision("none", None)


def test_rejection_majority():
    assert decide([out(0, rejected=True), out(1, rejected=True), out(2, rejected=True), out(3, A)], 5) == Decision("rejected", None)
    assert decide([out(0, rejected=True), out(1, rejected=True), out(2, A)], 5) == Decision("answer", 2)


def test_rejection_requires_greedy_candidate_rejected():
    rejected = [out(1, rejected=True), out(2, rejected=True), out(3, rejected=True)]
    assert decide([out(0, A)] + rejected + [out(4, error="x")], 5) == Decision("answer", 0)
    assert decide([out(0, rejected=True)] + rejected[1:] + [out(3, rejected=True), out(4, A)], 5) == Decision("rejected", None)
