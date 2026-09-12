import pytest

from src.providers.retry import call_with_retries


class _Retryable(Exception):
    pass


class _Fatal(Exception):
    pass


def test_succeeds_after_retryable_failures():
    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Retryable("boom")
        return "ok"

    result = call_with_retries(
        flaky, is_retryable=lambda exc: isinstance(exc, _Retryable), sleep=sleeps.append
    )

    assert result == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_raises_after_exhausting_retries():
    def always_fails():
        raise _Retryable("boom")

    with pytest.raises(_Retryable):
        call_with_retries(
            always_fails, is_retryable=lambda exc: True, retries=2, sleep=lambda _: None
        )


def test_non_retryable_raises_immediately():
    calls = {"n": 0}

    def fails_once():
        calls["n"] += 1
        raise _Fatal("nope")

    with pytest.raises(_Fatal):
        call_with_retries(fails_once, is_retryable=lambda exc: False, sleep=lambda _: None)

    assert calls["n"] == 1
