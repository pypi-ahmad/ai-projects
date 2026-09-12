import json

from src.eval.summarize import render_markdown, summarize_run


def _write_jsonl(path, *rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _build_run(tmp_path):
    dataset_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        dataset_path,
        {"id": "c1", "suite": "smoke", "input": {"user": "x"}, "tags": ["a", "b"]},
        {"id": "c2", "suite": "smoke", "input": {"user": "x"}, "tags": ["a"]},
        {"id": "c3", "suite": "regression", "input": {"user": "x"}, "tags": ["b"]},
    )

    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "candidates.jsonl",
        {
            "case_id": "c1",
            "text": "4",
            "model": "m",
            "provider": "p",
            "latency_ms": 100.0,
            "error": None,
        },
        {
            "case_id": "c2",
            "text": None,
            "model": "m",
            "provider": "p",
            "latency_ms": 200.0,
            "error": "boom",
        },
        {
            "case_id": "c3",
            "text": "5",
            "model": "m",
            "provider": "p",
            "latency_ms": 300.0,
            "error": None,
        },
    )
    _write_jsonl(
        run_dir / "rule_scores.jsonl",
        {
            "case_id": "c1",
            "metrics": [
                {"name": "latency_ms", "score": None, "passed": None, "detail": "100.0"},
                {"name": "exact_match", "score": 1.0, "passed": True, "detail": None},
            ],
        },
        {
            "case_id": "c2",
            "metrics": [{"name": "latency_ms", "score": None, "passed": None, "detail": "200.0"}],
        },
        {
            "case_id": "c3",
            "metrics": [
                {"name": "latency_ms", "score": None, "passed": None, "detail": "300.0"},
                {"name": "exact_match", "score": 0.0, "passed": False, "detail": "x"},
            ],
        },
    )
    _write_jsonl(
        run_dir / "judge_scores.jsonl",
        {
            "case_id": "c1",
            "rubric_id": "r",
            "judge_provider": "p",
            "judge_model": "m",
            "same_model_warning": False,
            "status": "ok",
            "scores": {"correctness": 0.9},
            "overall": 0.9,
            "passed": True,
            "rationale": "good",
            "evidence_spans": [],
            "error": None,
        },
    )
    return run_dir, dataset_path


def test_summarize_run_overall(tmp_path):
    run_dir, dataset_path = _build_run(tmp_path)

    summary = summarize_run(run_dir, dataset_path)

    assert summary.n_cases == 3
    assert summary.n_error == 1
    assert summary.mean_rule_pass_rate == 0.5  # mean(1.0, 0.0); c2 contributes nothing
    assert summary.mean_judge_overall == 0.9
    assert summary.p95_latency_ms == 290.0
    assert summary.dataset_path == str(dataset_path)
    assert len(summary.dataset_hash) == 64


def test_summarize_run_by_suite(tmp_path):
    run_dir, dataset_path = _build_run(tmp_path)

    summary = summarize_run(run_dir, dataset_path)

    assert set(summary.by_suite) == {"smoke", "regression"}
    assert summary.by_suite["smoke"].n_cases == 2
    assert summary.by_suite["smoke"].n_error == 1
    assert summary.by_suite["smoke"].mean_rule_pass_rate == 1.0
    assert summary.by_suite["regression"].n_cases == 1
    assert summary.by_suite["regression"].mean_rule_pass_rate == 0.0
    assert summary.by_suite["regression"].mean_judge_overall is None


def test_summarize_run_by_tag(tmp_path):
    run_dir, dataset_path = _build_run(tmp_path)

    summary = summarize_run(run_dir, dataset_path)

    assert set(summary.by_tag) == {"a", "b"}
    assert summary.by_tag["a"].n_cases == 2
    assert summary.by_tag["b"].n_cases == 2
    assert summary.by_tag["b"].mean_rule_pass_rate == 0.5


def test_summarize_run_excludes_skipped_cases(tmp_path):
    dataset_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        dataset_path,
        {"id": "c1", "suite": "smoke", "input": {"user": "x"}},
        {"id": "c2", "suite": "smoke", "input": {"user": "x"}},
    )
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "candidates.jsonl",
        {
            "case_id": "c1",
            "text": "4",
            "model": "m",
            "provider": "p",
            "latency_ms": 100.0,
            "error": None,
        },
        {
            "case_id": "c2",
            "text": None,
            "model": "m",
            "provider": "p",
            "latency_ms": 0.0,
            "error": None,
            "skip_reason": "needs_provider='ollama', running with 'p'",
        },
    )

    summary = summarize_run(run_dir, dataset_path)

    assert summary.n_cases == 1  # c2 excluded entirely, not counted as an error either
    assert summary.n_error == 0


def test_render_markdown_contains_key_sections(tmp_path):
    run_dir, dataset_path = _build_run(tmp_path)
    summary = summarize_run(run_dir, dataset_path)

    markdown = render_markdown(summary)

    assert "# Run Summary" in markdown
    assert "By suite" in markdown
    assert "By tag" in markdown
    assert "50.0%" in markdown  # overall mean rule pass rate
