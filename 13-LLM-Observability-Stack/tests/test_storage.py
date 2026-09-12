from pathlib import Path

import pytest

from obs_legacy import storage
from obs_legacy.models import Alert, TraceRecord, new_trace_id, utc_now_iso


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "data" / "obs.db")


def _make_trace(**overrides: object) -> TraceRecord:
    defaults = {
        "trace_id": new_trace_id(),
        "ts": utc_now_iso(),
        "provider": "ollama",
        "model": "qwen3.5:0.8b",
        "prompt_hash": "abc123",
        "prompt_preview": "hi",
        "response_hash": "def456",
        "response_preview": "hello",
        "tokens_in": 3,
        "tokens_out": 5,
        "latency_ms": 120.5,
        "cost_usd": 0.0,
        "priced": True,
        "status": "ok",
        "error": None,
    }
    defaults.update(overrides)
    return TraceRecord(**defaults)


def test_save_and_load_trace() -> None:
    trace = _make_trace()
    storage.save_trace(trace)

    rows = storage.load_traces()
    assert len(rows) == 1
    assert rows[0]["model"] == "qwen3.5:0.8b"
    assert rows[0]["priced"] == 1

    jsonl_files = list((storage.DATA_DIR / "traces").glob("*.jsonl"))
    assert len(jsonl_files) == 1


def test_save_and_load_alert() -> None:
    trace = _make_trace()
    storage.save_trace(trace)
    alert = Alert(
        trace_id=trace.trace_id,
        ts=utc_now_iso(),
        rule="latency_threshold",
        severity="warning",
        message="latency exceeded threshold",
    )
    storage.save_alert(alert)

    rows = storage.load_alerts()
    assert len(rows) == 1
    assert rows[0]["rule"] == "latency_threshold"

    jsonl_files = list((storage.DATA_DIR / "alerts").glob("*.jsonl"))
    assert len(jsonl_files) == 1


def test_trace_id_must_be_unique() -> None:
    trace = _make_trace()
    storage.save_trace(trace)
    with pytest.raises(Exception, match="UNIQUE"):
        storage.save_trace(trace)
