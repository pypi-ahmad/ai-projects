import pytest

from obs.providers.base import CompletionResult
from obs.providers.client import TracedClient
from obs.trace import clear_finished_traces, get_finished_traces
from obs.trace import tracer as tracer_module


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_module, "_exporters", [])
    clear_finished_traces()


class _FakeAdapter:
    def __init__(self, result: CompletionResult) -> None:
        self._result = result
        self.received_messages: list[dict] | None = None
        self.received_model: str | None = None

    def complete(self, messages: list[dict], model: str) -> CompletionResult:
        self.received_messages = messages
        self.received_model = model
        return self._result


def test_complete_records_usage_and_ttft_and_returns_trace_id() -> None:
    fake_result = CompletionResult(text="hi there", in_tokens=5, out_tokens=7, ttft_ms=12.5)
    adapter = _FakeAdapter(fake_result)
    client = TracedClient({"fake": adapter})

    result = client.complete([{"role": "user", "content": "hello"}], "fake", "fake-model")

    assert result.text == "hi there"
    assert result.in_tokens == 5
    assert result.out_tokens == 7
    assert result.ttft_ms == 12.5
    assert result.trace_id

    traces = get_finished_traces()
    assert len(traces) == 1
    span = traces[0].spans[0]
    assert span.name == "generate"
    assert span.kind == "client"
    assert span.provider == "fake"
    assert span.model == "fake-model"
    assert span.usage is not None
    assert span.usage.in_tokens == 5
    assert span.status == "ok"
    assert adapter.received_model == "fake-model"


def test_complete_unknown_provider_raises() -> None:
    client = TracedClient({})
    with pytest.raises(ValueError, match="no adapter registered"):
        client.complete([{"role": "user", "content": "hi"}], "nope", "m")


def test_complete_still_exports_trace_on_adapter_failure() -> None:
    class _BoomAdapter:
        def complete(self, messages: list[dict], model: str) -> CompletionResult:  # noqa: ARG002
            msg = "adapter exploded"
            raise RuntimeError(msg)

    client = TracedClient({"boom": _BoomAdapter()})
    with pytest.raises(RuntimeError, match="adapter exploded"):
        client.complete([{"role": "user", "content": "hi"}], "boom", "m")

    traces = get_finished_traces()
    assert len(traces) == 1
    assert traces[0].spans[0].status == "error"
