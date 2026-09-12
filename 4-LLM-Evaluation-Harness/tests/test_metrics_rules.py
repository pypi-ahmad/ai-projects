from src.metrics.rules import (
    contains_all,
    contains_any,
    exact_match,
    forbidden_any,
    json_parse_ok,
    latency_ms_passthrough,
    length_tokens_approx,
    regex_match,
)


def test_exact_match_passes_with_normalization():
    result = exact_match("  The Answer  is\n4 ", "the answer is 4")
    assert result.passed is True
    assert result.score == 1.0


def test_exact_match_fails_on_different_text():
    result = exact_match("4", "5")
    assert result.passed is False
    assert result.score == 0.0
    assert "expected" in result.detail


def test_exact_match_case_sensitive_flag():
    result = exact_match("Yes", "yes", case_sensitive=True)
    assert result.passed is False


def test_contains_all_passes_when_every_phrase_present():
    result = contains_all("Jupiter is the largest planet.", ["jupiter", "largest"])
    assert result.passed is True


def test_contains_all_fails_when_one_missing():
    result = contains_all("Jupiter is a planet.", ["jupiter", "largest"])
    assert result.passed is False
    assert "largest" in result.detail


def test_contains_any_passes_with_one_match():
    result = contains_any("It is Jupiter.", ["saturn", "jupiter"])
    assert result.passed is True


def test_contains_any_fails_with_no_match():
    result = contains_any("It is Mars.", ["saturn", "jupiter"])
    assert result.passed is False


def test_forbidden_any_passes_when_absent():
    result = forbidden_any("Use HTTP for this.", ["chrome", "firefox"])
    assert result.passed is True


def test_forbidden_any_fails_when_present():
    result = forbidden_any("Open it in Chrome.", ["chrome", "firefox"])
    assert result.passed is False
    assert "chrome" in result.detail.lower()


def test_regex_match_passes_on_match():
    result = regex_match("Order #12345 shipped", r"#\d+")
    assert result.passed is True


def test_regex_match_fails_without_match():
    result = regex_match("no order number here", r"#\d+")
    assert result.passed is False


def test_json_parse_ok_passes_on_valid_json():
    result = json_parse_ok('{"ok": true}')
    assert result.passed is True
    assert result.score == 1.0


def test_json_parse_ok_fails_on_free_text():
    result = json_parse_ok("Sure, the answer is yes.")
    assert result.passed is False
    assert result.score == 0.0


def test_length_tokens_approx_is_informational():
    result = length_tokens_approx("one two three")
    assert result.score is None
    assert result.passed is None
    assert "3" in result.detail


def test_latency_ms_passthrough_is_informational():
    result = latency_ms_passthrough(123.456)
    assert result.score is None
    assert result.passed is None
    assert result.detail == "123.5"
