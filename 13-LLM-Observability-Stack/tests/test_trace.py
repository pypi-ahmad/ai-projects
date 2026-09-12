import pytest

from obs.trace import Tracer, clear_finished_traces, get_finished_traces, register_exporter
from obs.trace import tracer as tracer_module


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    clear_finished_traces()


def test_nested_spans_share_trace_and_set_parent_id() -> None:
    with Tracer.start("request") as root, root.child("generate") as child:
        pass

    traces = get_finished_traces()
    assert len(traces) == 1
    trace = traces[0]
    assert len(trace.spans) == 2

    child_span = next(s for s in trace.spans if s.name == "generate")
    root_span = next(s for s in trace.spans if s.name == "request")

    assert root_span.ctx.parent_id is None
    assert child_span.ctx.parent_id == root_span.ctx.span_id
    assert child_span.ctx.trace_id == root_span.ctx.trace_id == trace.trace_id
    assert child_span.ctx.span_id == child.span_id


def test_exception_marks_status_error_and_still_exports() -> None:
    with (
        pytest.raises(ValueError, match="boom"),
        Tracer.start("request") as root,
        root.child("generate"),
    ):
        raise ValueError("boom")

    traces = get_finished_traces()
    assert len(traces) == 1
    trace = traces[0]

    child_span = next(s for s in trace.spans if s.name == "generate")
    root_span = next(s for s in trace.spans if s.name == "request")

    assert child_span.status == "error"
    assert child_span.error == "boom"
    # the unhandled exception propagates through the root span too
    assert root_span.status == "error"
    assert root_span.latency_ms is not None


def test_exporter_hook_called_on_root_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_module, "_exporters", [])
    received = []
    register_exporter(received.append)

    with Tracer.start("request"):
        pass

    assert len(received) == 1
    assert received[0].spans[0].name == "request"


def test_redaction_default_hides_full_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OBS_STORE_PROMPTS", raising=False)
    with Tracer.start("request") as span:
        span.set_prompt("a very long prompt " * 10)

    trace = get_finished_traces()[0]
    root_span = trace.spans[0]
    assert root_span.attrs["prompt_hash"] is not None
    assert root_span.attrs["prompt_preview"] == ("a very long prompt " * 10)[:120]
    assert "full_prompt" not in root_span.attrs


def test_redaction_opt_in_stores_full_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBS_STORE_PROMPTS", "true")
    with Tracer.start("request") as span:
        span.set_prompt("hello world")

    trace = get_finished_traces()[0]
    root_span = trace.spans[0]
    assert root_span.attrs["full_prompt"] == "hello world"


def test_set_assigns_known_fields_and_extra_to_attrs() -> None:
    with Tracer.start("request") as span:
        span.set(model="qwen3.5:0.8b", provider="ollama", route="/chat")

    trace = get_finished_traces()[0]
    root_span = trace.spans[0]
    assert root_span.model == "qwen3.5:0.8b"
    assert root_span.provider == "ollama"
    assert root_span.attrs["route"] == "/chat"


def test_set_usage() -> None:
    with Tracer.start("request") as span:
        span.set_usage(in_tokens=10, out_tokens=20, cost_est=0.0)

    trace = get_finished_traces()[0]
    root_span = trace.spans[0]
    assert root_span.usage is not None
    assert root_span.usage.in_tokens == 10
    assert root_span.usage.out_tokens == 20
