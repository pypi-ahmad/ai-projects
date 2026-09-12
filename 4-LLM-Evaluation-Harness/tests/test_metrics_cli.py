import json

from src.metrics.__main__ import main


def _write_jsonl(path, *rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_cli_joins_candidates_and_dataset(tmp_path, capsys):
    dataset_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        dataset_path,
        {"id": "c1", "suite": "smoke", "input": {"user": "2+2?"}, "expected": {"answer": "4"}},
        {
            "id": "c2",
            "suite": "smoke",
            "input": {"user": "json?"},
            "expected": {"json_schema_name": "ok_flag"},
        },
    )
    candidates_path = tmp_path / "candidates.jsonl"
    _write_jsonl(
        candidates_path,
        {
            "case_id": "c1",
            "text": "4",
            "model": "m",
            "provider": "p",
            "latency_ms": 1.0,
            "error": None,
        },
        {
            "case_id": "c2",
            "text": "not json",
            "model": "m",
            "provider": "p",
            "latency_ms": 2.0,
            "error": None,
        },
    )
    out_path = tmp_path / "rule_scores.jsonl"

    exit_code = main(
        [
            "--candidates",
            str(candidates_path),
            "--dataset",
            str(dataset_path),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    scores = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert [s["case_id"] for s in scores] == ["c1", "c2"]
    c1_metrics = {m["name"]: m for m in scores[0]["metrics"]}
    assert c1_metrics["exact_match"]["passed"] is True
    c2_metrics = {m["name"]: m for m in scores[1]["metrics"]}
    assert c2_metrics["json_parse_ok"]["passed"] is False


def test_cli_warns_and_skips_unmatched_candidate(tmp_path, capsys):
    dataset_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        dataset_path,
        {"id": "c1", "suite": "smoke", "input": {"user": "hi"}, "expected": {"answer": "4"}},
    )
    candidates_path = tmp_path / "candidates.jsonl"
    _write_jsonl(
        candidates_path,
        {
            "case_id": "unknown",
            "text": "x",
            "model": "m",
            "provider": "p",
            "latency_ms": 1.0,
            "error": None,
        },
    )
    out_path = tmp_path / "rule_scores.jsonl"

    exit_code = main(
        [
            "--candidates",
            str(candidates_path),
            "--dataset",
            str(dataset_path),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    assert out_path.read_text() == ""
    assert "unknown" in capsys.readouterr().err


def test_cli_skips_records_with_skip_reason(tmp_path):
    dataset_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        dataset_path,
        {"id": "c1", "suite": "smoke", "input": {"user": "hi"}, "expected": {"answer": "4"}},
    )
    candidates_path = tmp_path / "candidates.jsonl"
    _write_jsonl(
        candidates_path,
        {
            "case_id": "c1",
            "text": None,
            "model": "m",
            "provider": "p",
            "latency_ms": 0.0,
            "error": None,
            "skip_reason": "needs_provider='ollama', running with 'p'",
        },
    )
    out_path = tmp_path / "rule_scores.jsonl"

    exit_code = main(
        [
            "--candidates",
            str(candidates_path),
            "--dataset",
            str(dataset_path),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    assert out_path.read_text() == ""
