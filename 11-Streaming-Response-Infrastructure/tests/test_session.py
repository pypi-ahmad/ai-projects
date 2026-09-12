import time

from stream.providers.fake import FakeProvider
from stream.session import StreamSession


def test_replay_after_id_returns_only_newer_events() -> None:
    session = StreamSession(id="s1")
    session.append("a")
    session.append("b")
    session.append("c")

    replayed = session.replay(after_id=1)

    assert [e.data for e in replayed] == ["b", "c"]
    assert all(e.id > 1 for e in replayed)


def test_bounded_deque_drops_oldest_and_counts_dropped() -> None:
    session = StreamSession(id="s2", max_events=2)
    session.append("a")
    session.append("b")
    session.append("c")  # evicts "a"

    assert [e.data for e in session.replay(after_id=0)] == ["b", "c"]
    assert session.dropped_count == 1

    session.append("d")  # evicts "b"

    assert [e.data for e in session.replay(after_id=0)] == ["c", "d"]
    assert session.dropped_count == 2


def test_ttft_set_once_on_first_token() -> None:
    session = StreamSession(id="s3")
    assert session.metrics().ttft_ms is None

    session.append("a")
    first_ttft = session.metrics().ttft_ms
    assert first_ttft is not None

    session.append("b")

    assert session.metrics().ttft_ms == first_ttft


def test_complete_sets_done_reason_and_token_count() -> None:
    session = StreamSession(id="s4")
    session.append("a")
    session.complete()

    metrics = session.metrics()
    assert metrics.done_reason == "complete"
    assert metrics.token_count == 1


def test_fail_sets_done_reason_to_code() -> None:
    session = StreamSession(id="s5")
    session.fail("provider_error")

    assert session.metrics().done_reason == "provider_error"


def test_ttl_eviction_counts_dropped() -> None:
    session = StreamSession(id="s6", ttl_s=0.01)
    session.append("a")
    time.sleep(0.02)
    session.append("b")  # triggers TTL eviction of "a" before appending "b"

    assert session.dropped_count == 1
    assert [e.data for e in session.replay(after_id=0)] == ["b"]


async def test_fake_provider_feeds_session() -> None:
    session = StreamSession(id="s7")
    provider = FakeProvider(tokens=["x", "y", "z"])

    async for token in provider:
        session.append(token)
    session.complete()

    metrics = session.metrics()
    assert metrics.token_count == 3
    assert metrics.done_reason == "complete"
