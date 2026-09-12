import asyncio

from stream.config import BackpressureConfig
from stream.providers.fake import FakeProvider
from stream.session import StreamSession, pump


async def test_high_watermark_pauses_pull_until_drained() -> None:
    session = StreamSession(id="bp1", max_events=100)
    config = BackpressureConfig(high_watermark=3, low_watermark=1, poll_interval_s=0.005)
    provider = FakeProvider(tokens=["a", "b", "c", "d", "e"])

    task = asyncio.create_task(pump(provider, session, config, can_pause=True))
    await asyncio.sleep(0.05)  # let it fill to the watermark and block

    assert not task.done()
    assert session.buffer_len == config.high_watermark

    session.ack(2)  # drains to <= low_watermark
    await asyncio.wait_for(task, timeout=1.0)

    assert session.metrics().token_count == 5


async def test_drop_newest_when_provider_cannot_pause() -> None:
    session = StreamSession(id="bp2", max_events=100)
    config = BackpressureConfig(high_watermark=2, low_watermark=1, drop_oldest_replayable=False)
    provider = FakeProvider(tokens=["a", "b", "c", "d"])

    await pump(provider, session, config, can_pause=False)

    # a, b fill to high_watermark; c, d arrive with nothing acked and no way
    # to pause, so they're discarded before ever being buffered.
    assert session.metrics().token_count == 2
    assert session.dropped_count == 2
    assert [e.data for e in session.replay(after_id=0)] == ["a", "b"]


async def test_drop_oldest_replayable_when_configured() -> None:
    session = StreamSession(id="bp3", max_events=100)
    config = BackpressureConfig(high_watermark=2, low_watermark=1, drop_oldest_replayable=True)
    provider = FakeProvider(tokens=["a", "b", "c"])

    await pump(provider, session, config, can_pause=False)

    # "a" is evicted to make room for "c" instead of dropping "c" itself.
    assert session.dropped_count == 1
    assert [e.data for e in session.replay(after_id=0)] == ["b", "c"]
