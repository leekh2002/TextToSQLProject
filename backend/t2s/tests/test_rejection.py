from backend.validate import is_safety_rejection


def test_is_safety_rejection_matches_ambiguity_and_validator_reasons():
    assert is_safety_rejection("질문이 모호합니다.")
    assert is_safety_rejection("SELECT 문만 허용됩니다.")
    assert is_safety_rejection("  SELECT 문만 허용됩니다.\n")
    assert not is_safety_rejection("기본 LIMIT가 필요합니다.")
    assert not is_safety_rejection(None)
