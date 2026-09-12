import json

from src.judge import __main__ as judge_main
from src.providers.base import ProviderSpec

VALID_VERDICT_JSON = json.dumps(
    {
        "scores": {"correctness": 1.0, "completeness": 1.0},
        "overall": 1.0,
        "pass": True,
        "rationale": "Correct.",
        "evidence_spans": ["4"],
    }
)


def _write_jsonl(path, *rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


class _FakeJudgeProvider:
    def __init__(self):
        self.unload_calls: list[str] = []

    def complete(self, *, system, user, model, think=None):
        return VALID_VERDICT_JSON

    def unload(self, model: str) -> None:
        self.unload_calls.append(model)


def test_cli_writes_judge_scores_to_default_out_path(tmp_path, monkeypatch, capsys):
    dataset_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        dataset_path,
        {
            "id": "c1",
            "suite": "smoke",
            "input": {"user": "2+2?"},
            "judge": {"rubric_id": "test_rubric", "required": True},
        },
        {"id": "c2", "suite": "smoke", "input": {"user": "no judge here"}},
    )
    run_dir = tmp_path / "reports" / "run1"
    run_dir.mkdir(parents=True)
    candidates_path = run_dir / "candidates.jsonl"
    _write_jsonl(
        candidates_path,
        {
            "case_id": "c1",
            "text": "4",
            "model": "m",
            "provider": "agnes",
            "latency_ms": 1.0,
            "error": None,
        },
        {
            "case_id": "c2",
            "text": "hi",
            "model": "m",
            "provider": "agnes",
            "latency_ms": 1.0,
            "error": None,
        },
    )

    rubrics_dir = tmp_path / "rubrics"
    rubrics_dir.mkdir()
    (rubrics_dir / "test_rubric.yaml").write_text(
        "id: test_rubric\nversion: 1\ndimensions:\n"
        "  - {name: correctness, description: x, weight: 0.5}\n"
        "  - {name: completeness, description: y, weight: 0.5}\n",
        encoding="utf-8",
    )

    fake_provider = _FakeJudgeProvider()
    monkeypatch.setitem(
        judge_main.PROVIDERS,
        "ollama",
        ProviderSpec(
            factory=lambda: fake_provider,
            default_model="granite4.1:3b",
            allowed_models=("granite4.1:3b",),
        ),
    )

    exit_code = judge_main.main(
        [
            "--candidates",
            str(candidates_path),
            "--dataset",
            str(dataset_path),
            "--provider",
            "ollama",
            "--model",
            "granite4.1:3b",
            "--rubric",
            "test_rubric",
            "--rubrics-dir",
            str(rubrics_dir),
        ]
    )

    assert exit_code == 0
    out_path = run_dir / "judge_scores.jsonl"
    records = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert len(records) == 1  # c2 has no judge -> skipped
    assert records[0]["case_id"] == "c1"
    assert records[0]["status"] == "ok"
    assert records[0]["passed"] is True

    out = capsys.readouterr()
    assert "Wrote 1 judge score" in out.out
    assert "self-judging" not in out.err  # candidate provider (agnes) != judge provider (ollama)
    assert fake_provider.unload_calls == ["granite4.1:3b"]  # ollama judge model unloaded after use
