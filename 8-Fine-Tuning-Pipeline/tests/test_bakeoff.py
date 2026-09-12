# Pure functions only (aggregate_metrics, find_disagreements, write_bakeoff_md,
# write_adapter_missing_md) on hand-built rows — no model. LocalAdapterModel and judge_one/
# run_judge are not covered here; see README.md "Known limitations".
from pathlib import Path

from src.data.schema import TicketTarget
from src.eval.baseline import FIELDS, aggregate_metrics
from src.eval.bakeoff import find_disagreements, write_adapter_missing_md, write_bakeoff_md


def make_target(priority="high", product="billing", sentiment="negative", next_action="escalate"):
    return TicketTarget(priority=priority, product=product, sentiment=sentiment, next_action=next_action)


def make_row(idx: int, gold: TicketTarget, pred: TicketTarget | None) -> dict:
    field_match = {f: pred is not None and getattr(pred, f) == getattr(gold, f) for f in FIELDS}
    return {
        "idx": idx,
        "input": f"ticket {idx}",
        "gold": gold,
        "pred": pred,
        "json_valid": pred is not None,
        "field_match": field_match,
        "full_exact": all(field_match.values()),
    }


def test_aggregate_metrics_on_canned_rows():
    gold = make_target()
    rows = [
        make_row(0, gold, make_target()),  # exact match
        make_row(1, gold, make_target(priority="low")),  # 1 field wrong
        make_row(2, gold, None),  # invalid JSON
    ]

    metrics = aggregate_metrics(rows)

    assert metrics["n_items"] == 3
    assert metrics["json_valid_rate"] == 2 / 3
    assert metrics["full_exact_rate"] == 1 / 3
    assert metrics["field_micro_f1"] == 7 / 12
    assert metrics["per_field_accuracy"]["priority"] == 1 / 3


def test_aggregate_metrics_empty():
    metrics = aggregate_metrics([])
    assert metrics["n_items"] == 0
    assert metrics["json_valid_rate"] == 0.0
    assert metrics["full_exact_rate"] == 0.0
    assert metrics["field_micro_f1"] == 0.0


def test_find_disagreements_flags_differing_predictions():
    gold = make_target()
    baseline_rows = [
        make_row(0, gold, make_target()),
        make_row(1, gold, make_target(priority="low")),
        make_row(2, gold, None),
    ]
    lora_rows = [
        make_row(0, gold, make_target()),  # same as baseline -> no disagreement
        make_row(1, gold, make_target()),  # differs from baseline's wrong pred
        make_row(2, gold, None),  # both invalid -> both None -> no disagreement
    ]

    assert find_disagreements(baseline_rows, lora_rows) == [1]


def test_write_bakeoff_md_states_when_lora_lost(tmp_path: Path):
    gold = make_target()
    baseline_rows = [make_row(i, gold, make_target()) for i in range(4)]  # all exact
    lora_rows = [make_row(i, gold, make_target(priority="low")) for i in range(4)]  # all wrong

    baseline_report = {"model": "qwen3.5:0.8b", **aggregate_metrics(baseline_rows)}
    lora_report = {"model": "lora-run", **aggregate_metrics(lora_rows)}

    out_path = tmp_path / "bakeoff.md"
    write_bakeoff_md(out_path, baseline_report, None, lora_report, None)

    text = out_path.read_text(encoding="utf-8")
    assert "did NOT beat the frozen baseline" in text
    assert "regressed" in text.lower()


def test_write_bakeoff_md_states_when_lora_won(tmp_path: Path):
    gold = make_target()
    baseline_rows = [make_row(i, gold, make_target(priority="low")) for i in range(4)]  # all wrong
    lora_rows = [make_row(i, gold, make_target()) for i in range(4)]  # all exact

    baseline_report = {"model": "qwen3.5:0.8b", **aggregate_metrics(baseline_rows)}
    lora_report = {"model": "lora-run", **aggregate_metrics(lora_rows)}

    out_path = tmp_path / "bakeoff.md"
    write_bakeoff_md(out_path, baseline_report, None, lora_report, None)

    text = out_path.read_text(encoding="utf-8")
    assert "did NOT beat" not in text
    assert "improved" in text.lower()


def test_write_adapter_missing_md_has_no_fake_scores(tmp_path: Path):
    out_path = tmp_path / "bakeoff.md"
    missing_adapter = tmp_path / "outputs" / "adapters" / "does-not-exist"

    write_adapter_missing_md(out_path, missing_adapter)

    text = out_path.read_text(encoding="utf-8")
    assert "adapter missing" in text
    assert str(missing_adapter) in text
    # no numeric metric table should appear when there's nothing to score
    assert "json_valid_rate" not in text
    assert "full_exact_rate" not in text
