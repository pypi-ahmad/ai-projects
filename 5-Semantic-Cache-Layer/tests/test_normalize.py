import pytest

from src.cache.normalize import normalize_query


def test_strips_and_collapses_whitespace():
    assert normalize_query("  hello   world  ") == "hello world"
    assert normalize_query("hello\n\tworld") == "hello world"


def test_lowercase_default_on():
    assert normalize_query("Hello World") == "hello world"


def test_lowercase_can_be_disabled():
    assert normalize_query("Hello World", lowercase=False) == "Hello World"


def test_trailing_punct_kept_by_default():
    assert normalize_query("What is caching?") == "what is caching?"


def test_trailing_punct_dropped_when_enabled():
    assert normalize_query("What is caching?", drop_trailing_punct=True) == "what is caching"
    assert normalize_query("Wait...", drop_trailing_punct=True) == "wait"


def test_does_not_stem():
    assert normalize_query("running") != normalize_query("run")
    assert normalize_query("caches") != normalize_query("cache")


@pytest.mark.parametrize(
    "text",
    ["Hello, World!", "  multiple   spaces  ", "MiXeD CaSe", "trailing.punct."],
)
def test_normalize_is_idempotent(text):
    once = normalize_query(text)
    twice = normalize_query(once)
    assert once == twice


def test_equivalent_inputs_converge():
    assert normalize_query("  Hello   World  ") == normalize_query("hello world")
