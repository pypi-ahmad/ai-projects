import json

from src.gate import __main__ as gate_main


def _write_jsonl(path, *rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _write_summary(run_dir, **overrides):
    data = {
        "run_id": run_dir.name,
        "dataset_path": "datasets/golden/smoke.jsonl",
        "dataset_hash": "abc",
        "n_cases": 5,
        "n_error": 0,
        "mean_rule_pass_rate": 0.9,
        "mean_judge_overall": 0.9,
        "p95_latency_ms": 1000.0,
        "by_suite": {},
        "by_tag": {},
    }
    data.update(overrides)
    (run_dir / "summary.json").write_text(json.dumps(data), encoding="utf-8")


def _write_config(path, **overrides):
    config = {"min_rule_pass_rate": 0.5, "allow_missing_judge": True}
    config.update(overrides)
    path.write_text("\n".join(f"{k}: {v}" for k, v in config.items()), encoding="utf-8")


def test_evaluate_passes(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_summary(run_dir)
    config_path = tmp_path / "gate.yaml"
    _write_config(config_path)

    exit_code = gate_main.main(
        [
            "--run",
            str(run_dir),
            "--baseline",
            str(tmp_path / "no_such_baseline.json"),
            "--config",
            str(config_path),
        ]
    )

    assert exit_code == gate_main.EXIT_PASS


def test_evaluate_fails_gate(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_summary(run_dir, mean_rule_pass_rate=0.1)
    config_path = tmp_path / "gate.yaml"
    _write_config(config_path)

    exit_code = gate_main.main(
        [
            "--run",
            str(run_dir),
            "--baseline",
            str(tmp_path / "no_such_baseline.json"),
            "--config",
            str(config_path),
        ]
    )

    assert exit_code == gate_main.EXIT_GATE_FAIL


def test_evaluate_missing_summary_is_infra_error(tmp_path):
    run_dir = tmp_path / "empty_run"
    run_dir.mkdir()
    config_path = tmp_path / "gate.yaml"
    _write_config(config_path)

    exit_code = gate_main.main(
        [
            "--run",
            str(run_dir),
            "--baseline",
            str(tmp_path / "no_such_baseline.json"),
            "--config",
            str(config_path),
        ]
    )

    assert exit_code == gate_main.EXIT_INFRA_ERROR


def test_evaluate_missing_config_is_infra_error(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_summary(run_dir)

    exit_code = gate_main.main(
        [
            "--run",
            str(run_dir),
            "--baseline",
            str(tmp_path / "no_such_baseline.json"),
            "--config",
            str(tmp_path / "no_such_config.yaml"),
        ]
    )

    assert exit_code == gate_main.EXIT_INFRA_ERROR


def test_accept_writes_baseline(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_summary(run_dir)
    _write_jsonl(
        run_dir / "candidates.jsonl",
        {
            "case_id": "c1",
            "text": "4",
            "model": "granite4.1:3b",
            "provider": "ollama",
            "latency_ms": 1.0,
            "error": None,
        },
    )
    baseline_path = tmp_path / "baselines" / "current.json"

    exit_code = gate_main.main(
        ["--accept", str(run_dir), "--baseline", str(baseline_path)]
    )

    assert exit_code == gate_main.EXIT_PASS
    data = json.loads(baseline_path.read_text())
    assert data["config"]["candidate_model"] == "granite4.1:3b"
    assert data["summary"]["run_id"] == "run1"


def test_evaluate_warns_on_dataset_hash_mismatch(tmp_path, capsys):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_summary(run_dir, dataset_hash="new-hash")
    config_path = tmp_path / "gate.yaml"
    _write_config(config_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "summary": {
                    "run_id": "old-run",
                    "dataset_path": "datasets/golden/smoke.jsonl",
                    "dataset_hash": "old-hash",
                    "n_cases": 5,
                    "n_error": 0,
                    "mean_rule_pass_rate": 0.9,
                    "mean_judge_overall": 0.9,
                    "p95_latency_ms": 1000.0,
                    "by_suite": {},
                    "by_tag": {},
                },
                "config": {
                    "dataset_path": "datasets/golden/smoke.jsonl",
                    "dataset_hash": "old-hash",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = gate_main.main(
        ["--run", str(run_dir), "--baseline", str(baseline_path), "--config", str(config_path)]
    )

    assert exit_code == gate_main.EXIT_PASS
    assert "dataset has changed" in capsys.readouterr().err


def test_evaluate_no_warning_when_dataset_hash_matches(tmp_path, capsys):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_summary(run_dir, dataset_hash="same-hash")
    config_path = tmp_path / "gate.yaml"
    _write_config(config_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "summary": {
                    "run_id": "old-run",
                    "dataset_path": "datasets/golden/smoke.jsonl",
                    "dataset_hash": "same-hash",
                    "n_cases": 5,
                    "n_error": 0,
                    "mean_rule_pass_rate": 0.9,
                    "mean_judge_overall": 0.9,
                    "p95_latency_ms": 1000.0,
                    "by_suite": {},
                    "by_tag": {},
                },
                "config": {
                    "dataset_path": "datasets/golden/smoke.jsonl",
                    "dataset_hash": "same-hash",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = gate_main.main(
        ["--run", str(run_dir), "--baseline", str(baseline_path), "--config", str(config_path)]
    )

    assert exit_code == gate_main.EXIT_PASS
    assert "dataset has changed" not in capsys.readouterr().err


def test_accept_refused_under_ci(tmp_path, monkeypatch):
    monkeypatch.setenv("CI", "true")
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_summary(run_dir)
    baseline_path = tmp_path / "baselines" / "current.json"

    exit_code = gate_main.main(
        ["--accept", str(run_dir), "--baseline", str(baseline_path)]
    )

    assert exit_code == gate_main.EXIT_INFRA_ERROR
    assert not baseline_path.exists()
