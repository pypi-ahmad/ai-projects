from pathlib import Path

import pytest

from obs.alerts.evaluator import evaluate_once
from obs.alerts.models import Alert
from obs.alerts.stats import percentile
from obs.alerts.store import in_cooldown, list_alerts, save_alert
from obs.export.sqlite import SqliteExporter
from obs.trace import Tracer, clear_finished_traces, register_exporter
from obs.trace import tracer as tracer_module


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_module, "_exporters", [])
    clear_finished_traces()


def _write_span(*, status: str, model: str = "test-model", route: str = "/chat") -> None:
    """One trace: root "request" span + a "generate" child carrying model/provider."""
    if status == "error":
        with pytest.raises(ValueError, match="synthetic"), Tracer.start("request") as root:
            root.set_trace(route=route)
            with root.child("generate") as gen:
                gen.set(provider="ollama", model=model)
                raise ValueError("synthetic")
    else:
        with Tracer.start("request") as root:
            root.set_trace(route=route)
            with root.child("generate") as gen:
                gen.set(provider="ollama", model=model)


def _small_alerts_config(tmp_path: Path, *, threshold: float = 0.2, window_n: int = 10) -> Path:
    path = tmp_path / "alerts.yaml"
    path.write_text(
        f"""
cooldown_minutes: 30
rules:
  error_rate:
    enabled: true
    window_n: {window_n}
    threshold: {threshold}
    severity: critical
  latency_regression:
    enabled: false
  cost_sum_hour:
    enabled: false
  ttft_p50:
    enabled: false
  traffic_drop:
    enabled: false
  unpriced_burst:
    enabled: false
""",
        encoding="utf-8",
    )
    return path


def test_synthetic_spans_trip_error_rate_rule(tmp_path: Path) -> None:
    db_path = tmp_path / "obs.db"
    register_exporter(SqliteExporter(db_path))
    config_path = _small_alerts_config(tmp_path, threshold=0.2, window_n=10)

    # 2 ok, 3 error generate-spans on model=test-model -> error_rate 0.6 > 0.2
    for _ in range(2):
        _write_span(status="ok")
    for _ in range(3):
        _write_span(status="error")

    created = evaluate_once(config_path=config_path, db_path=db_path)

    assert len(created) == 1
    alert = created[0]
    assert alert.rule == "error_rate"
    assert alert.route == "/chat"
    assert alert.model == "test-model"
    assert alert.value == pytest.approx(0.6)
    assert alert.threshold == pytest.approx(0.2)
    assert len(alert.trace_ids) == 5  # 5 traces total, all sampled

    stored = list_alerts(db_path=db_path)
    assert len(stored) == 1


def test_cooldown_suppresses_second_alert(tmp_path: Path) -> None:
    db_path = tmp_path / "obs.db"
    register_exporter(SqliteExporter(db_path))
    config_path = _small_alerts_config(tmp_path, threshold=0.2, window_n=10)

    for _ in range(3):
        _write_span(status="error")

    first = evaluate_once(config_path=config_path, db_path=db_path)
    assert len(first) == 1

    # more errors keep coming in, same route+model, still within cooldown
    for _ in range(3):
        _write_span(status="error")
    second = evaluate_once(config_path=config_path, db_path=db_path)

    assert second == []
    assert len(list_alerts(db_path=db_path)) == 1


def test_no_alert_below_threshold(tmp_path: Path) -> None:
    db_path = tmp_path / "obs.db"
    register_exporter(SqliteExporter(db_path))
    config_path = _small_alerts_config(tmp_path, threshold=0.5, window_n=10)

    for _ in range(4):
        _write_span(status="ok")
    _write_span(status="error")  # error_rate 0.2, below 0.5 threshold

    created = evaluate_once(config_path=config_path, db_path=db_path)
    assert created == []


def test_percentile_matches_known_values() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 50) == pytest.approx(50.5, abs=1.0)
    assert percentile(values, 95) == pytest.approx(95.05, abs=1.0)
    assert percentile([42.0], 95) == 42.0
    assert percentile([], 50) is None


def test_in_cooldown_respects_route_and_window(tmp_path: Path) -> None:
    db_path = tmp_path / "obs.db"
    save_alert(
        Alert(
            rule="error_rate",
            severity="critical",
            route="/chat",
            model="m1",
            window="last_10",
            value=0.6,
            threshold=0.2,
            trace_ids=["t1"],
        ),
        db_path=db_path,
    )

    assert in_cooldown("error_rate", "/chat", cooldown_minutes=30, db_path=db_path)
    assert not in_cooldown("error_rate", "/other-route", cooldown_minutes=30, db_path=db_path)
    assert not in_cooldown("latency_regression", "/chat", cooldown_minutes=30, db_path=db_path)
    assert not in_cooldown("error_rate", "/chat", cooldown_minutes=0, db_path=db_path)
