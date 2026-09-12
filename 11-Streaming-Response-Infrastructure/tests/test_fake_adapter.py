from stream.metrics import time_stream, ttft_s
from stream.providers.base import TokenChunk
from stream.providers.fake import FakeAdapter


async def test_fake_adapter_yields_words_in_order_then_done() -> None:
    adapter = FakeAdapter(text="a b c", delay_s=0.01)
    chunks = [c async for c in adapter.stream(prompt="ignored")]
    assert [c.text for c in chunks] == ["a", " b", " c", ""]
    assert [c.done for c in chunks] == [False, False, False, True]


async def test_time_stream_reports_gaps_and_monotonic_elapsed() -> None:
    adapter = FakeAdapter(text="a b", delay_s=0.02)
    timed = [tc async for tc in time_stream(adapter.stream(prompt="x"))]
    assert timed[0].gap_s is None
    assert all(tc.gap_s is not None for tc in timed[1:])
    assert timed[-1].elapsed_s > timed[0].elapsed_s
    assert ttft_s(timed) == timed[0].elapsed_s


async def test_ttft_skips_leading_empty_chunks() -> None:
    async def chunks():
        yield TokenChunk(text="")
        yield TokenChunk(text="hi")

    timed = [tc async for tc in time_stream(chunks())]
    assert ttft_s(timed) == timed[1].elapsed_s


async def test_ttft_none_when_no_text_ever_arrives() -> None:
    async def chunks():
        yield TokenChunk(text="", done=True)

    timed = [tc async for tc in time_stream(chunks())]
    assert ttft_s(timed) is None
