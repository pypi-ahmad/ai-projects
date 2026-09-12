from pathlib import Path

import pytest

from obs.export import get_trace, query
from obs.export.jsonl import JsonlExporter
from obs.export.sqlite import SqliteExporter
from obs.trace import Tracer, clear_finished_traces, register_exporter
from obs.trace import tracer as tracer_module


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # obs.trace.tracer._exporters/_finished_traces are process-lifetime
    # module globals (see tracer.py) - without resetting them per test, an
    # exporter registered in one test would still fire in the next.
    monkeypatch.setattr(tracer_module, "_exporters", [])
    clear_finished_traces()


def _make_trace() -> str:
    with Tracer.start("request") as root:
        root.set(provider="ollama", model="qwen3.5:0.8b")
        root.set_trace(route="/chat")
        trace_id = root.trace_id
        with root.child("generate") as gen:
            gen.set(provider="ollama", model="qwen3.5:0.8b")
            gen.set_usage(in_tokens=10, out_tokens=20)
    return trace_id


def test_sqlite_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "obs.db"
    register_exporter(SqliteExporter(db_path))

    trace_id = _make_trace()

    loaded = get_trace(trace_id, db_path=db_path)
    assert loaded is not None
    assert loaded.trace_id == trace_id
    assert len(loaded.spans) == 2
    assert loaded.attrs["route"] == "/chat"

    gen_span = next(s for s in loaded.spans if s.name == "generate")
    root_span = next(s for s in loaded.spans if s.name == "request")
    assert gen_span.ctx.parent_id == root_span.ctx.span_id
    assert gen_span.usage is not None
    assert gen_span.usage.in_tokens == 10
    assert gen_span.usage.out_tokens == 20
    # qwen3.5:0.8b is priced at 0 (local Ollama compute) in config/prices.yaml
    assert gen_span.usage.cost_est == 0.0


def test_get_trace_missing_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "obs.db"
    register_exporter(SqliteExporter(db_path))
    _make_trace()

    assert get_trace("does-not-exist", db_path=db_path) is None


def test_query_filters_by_route_model_status(tmp_path: Path) -> None:
    db_path = tmp_path / "obs.db"
    register_exporter(SqliteExporter(db_path))
    _make_trace()

    by_route = query(route="/chat", db_path=db_path)
    assert len(by_route) == 2  # root + generate span

    by_model = query(model="qwen3.5:0.8b", db_path=db_path)
    assert len(by_model) == 2
    gen_row = next(r for r in by_model if r["name"] == "generate")
    assert gen_row["in_tokens"] == 10
    assert gen_row["out_tokens"] == 20
    assert gen_row["cost_est"] == 0.0
    assert gen_row["pricing"] == "PRICED"

    by_status = query(status="error", db_path=db_path)
    assert by_status == []

    by_missing_route = query(route="/nope", db_path=db_path)
    assert by_missing_route == []


def test_jsonl_exporter_writes_one_line_per_span(tmp_path: Path) -> None:
    base_dir = tmp_path / "traces"
    register_exporter(JsonlExporter(base_dir))

    _make_trace()

    files = list(base_dir.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # root span + generate span


def test_one_exporter_failing_does_not_block_the_other(tmp_path: Path) -> None:
    db_path = tmp_path / "obs.db"

    def broken_exporter(_trace: object) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    register_exporter(broken_exporter)
    register_exporter(SqliteExporter(db_path))

    trace_id = _make_trace()

    assert get_trace(trace_id, db_path=db_path) is not None
