# run_baseline/write_report against a canned ChatClient below — no real Ollama call.
from pathlib import Path

from src.data.schema import TicketExample
from src.eval.baseline import run_baseline, write_report

SYSTEM_PROMPT = "test system prompt"


def make_example(priority="high", product="billing", sentiment="negative", next_action="escalate"):
    return TicketExample(
        input="a ticket",
        target={
            "priority": priority,
            "product": product,
            "sentiment": sentiment,
            "next_action": next_action,
        },
        split="test",
        teacher_model="granite4.1:3b",
    )


class CannedChatModel:
    """Returns pre-scripted replies in order, one per call. No network."""

    model_name = "canned-model"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        reply = self.replies[self.calls]
        self.calls += 1
        return reply


def test_run_baseline_scores_exact_mismatch_and_invalid():
    examples = [make_example(), make_example(), make_example()]
    replies = [
        '{"priority": "high", "product": "billing", "sentiment": "negative", "next_action": "escalate"}',
        '{"priority": "low", "product": "billing", "sentiment": "negative", "next_action": "escalate"}',
        "not json at all",
    ]
    model = CannedChatModel(replies)

    report, rows = run_baseline(model, examples, SYSTEM_PROMPT)

    assert report["n_items"] == 3
    assert report["json_valid_rate"] == 2 / 3
    assert report["full_exact_rate"] == 1 / 3
    # item0: 4/4 correct, item1: 3/4 correct, item2: invalid -> 0/4. (4+3+0)/12
    assert report["field_micro_f1"] == 7 / 12
    assert rows[0]["full_exact"] is True
    assert rows[1]["field_match"]["priority"] is False
    assert rows[2]["json_valid"] is False
    assert rows[2]["pred"] is None


def test_write_report_omits_exact_matches_from_errors_csv(tmp_path: Path):
    examples = [make_example()]
    replies = [
        '{"priority": "high", "product": "billing", "sentiment": "negative", "next_action": "escalate"}'
    ]
    model = CannedChatModel(replies)
    report, rows = run_baseline(model, examples, SYSTEM_PROMPT)

    report_path, csv_path = write_report(
        report, rows, tmp_path, "qwen3.5:0.8b", Path("configs/baseline_prompt.txt")
    )

    assert report_path.name == "baseline_qwen3.5_0.8b.json"
    assert csv_path.name == "baseline_qwen3.5_0.8b_errors.csv"
    assert report_path.exists()
    # only the header line, since the one item was an exact match
    assert csv_path.read_text().strip().count("\n") == 0


def test_write_report_includes_mismatch_row(tmp_path: Path):
    examples = [make_example()]
    replies = ['{"priority": "low", "product": "billing", "sentiment": "negative", "next_action": "escalate"}']
    model = CannedChatModel(replies)
    report, rows = run_baseline(model, examples, SYSTEM_PROMPT)

    _, csv_path = write_report(report, rows, tmp_path, "qwen3.5:0.8b", Path("configs/baseline_prompt.txt"))

    lines = csv_path.read_text().strip().splitlines()
    assert len(lines) == 2  # header + 1 mismatch row
    assert "priority" in lines[1]
