import time

from stream.session import Event
from stream.sse import heartbeat, heartbeat_ticker, sse_format


def test_sse_format_token_event_is_valid_wire_bytes() -> None:
    event = Event(id=3, type="token", data="hi", ts_monotonic=0.0)

    assert sse_format(event) == b"event: token\nid: 3\ndata: hi\n\n"


def test_sse_format_splits_multiline_data_into_multiple_data_lines() -> None:
    event = Event(id=1, type="token", data="line one\nline two", ts_monotonic=0.0)

    assert sse_format(event) == b"event: token\nid: 1\ndata: line one\ndata: line two\n\n"


def test_sse_format_empty_data_still_emits_a_data_line() -> None:
    # Spec: an event with *no* data: field at all never dispatches, so
    # `done`/no-message `error` events still need one, even empty.
    event = Event(id=2, type="done", data="", ts_monotonic=0.0)

    assert sse_format(event) == b"event: done\nid: 2\ndata: \n\n"


def test_heartbeat_is_a_comment_line_terminated_by_blank_line() -> None:
    raw = heartbeat("ping")

    assert raw == b": ping\n\n"
    assert not raw.startswith(b"event:")
    assert not raw.startswith(b"data:")


async def test_heartbeat_ticker_emits_at_the_configured_interval() -> None:
    ticker = heartbeat_ticker(interval_ms=20)
    start = time.monotonic()

    first = await ticker.__anext__()
    elapsed_first = time.monotonic() - start
    second = await ticker.__anext__()
    elapsed_second = time.monotonic() - start

    assert first == heartbeat()
    assert second == heartbeat()
    assert elapsed_first >= 0.018
    assert elapsed_second >= 0.036
