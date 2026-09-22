"""Per-run ledgers and Sol pricing, with no process-global accumulator."""
import pytest
from src import usage


def test_record_and_totals():
    entries = []
    usage.record("parse_page", "gpt-6-sol", {
        "input_tokens": 1000, "output_tokens": 200,
        "input_token_details": {"cache_read": 300, "cache_write": 200},
    }, entries=entries)
    usage.record("parse_page", "gpt-6-sol", {
        "input_tokens": 500, "output_tokens": 100,
    }, entries=entries)
    assert usage.totals(entries) == {
        "input_tokens": 1500, "output_tokens": 300, "cached_tokens": 300, "cache_write_tokens": 200,
    }


def test_missing_usage_is_unknown():
    entries = []
    usage.record("parse_page", "gpt-6-sol", None, entries=entries)
    assert not entries[0]["usage_known"]
    assert usage.totals(entries) == dict(input_tokens=0, output_tokens=0, cached_tokens=0, cache_write_tokens=0)


def test_ledgers_do_not_share_entries():
    a, b = [], []
    usage.record("a", "gpt-6-sol", {"input_tokens": 10}, entries=a)
    usage.record("b", "gpt-6-sol", {"input_tokens": 20}, entries=b)
    assert [e["call"] for e in a] == ["a"]
    assert [e["call"] for e in b] == ["b"]


def test_cost_usd_uses_all_input_rates():
    totals = dict(input_tokens=3_000_000, output_tokens=1_000_000,
                  cached_tokens=1_000_000, cache_write_tokens=1_000_000)
    assert usage.cost_usd(totals) == pytest.approx(14.70)
    assert usage.session_cost_usd([totals, totals]) == pytest.approx(29.40)


def test_unknown_model_is_not_repriced_as_sol():
    with pytest.raises(KeyError):
        usage.cost_usd(dict(input_tokens=1, output_tokens=1), "legacy-model")
