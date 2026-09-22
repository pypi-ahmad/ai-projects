"""Tests for scripts/evaluate_prompts.py (docs/PROMPT-EVALUATION.md,
docs/PROMPTS.md) -- the offline/live prompt-comparison tool, not the active
graph. Covers the fixed six-page evaluation manifest, reference-based
scoring (table text isn't double-counted against its own plain-text
duplicate), and that a corrective re-run skips pages already known to be
content-filtered rather than re-submitting them.

Next: scripts/evaluate_prompts.py (outside src/, not part of the active
pipeline).
"""

import json
import sys
from types import SimpleNamespace

import pytest

from scripts import evaluate_prompts as evaluation
from scripts.evaluate_prompts import SAMPLES, plain_text, score_page
from src.layout import BBox, ParseBlock, ParsePage


def test_live_manifest_is_limited_to_approved_six_pages():
    assert SAMPLES == (
        ("Masked BadgeCare Plus_1", 1),
        ("Masked_Amerigroup_RealSolutions_1", 2),
        ("Masked_Amerigroup_RealSolutions_2", 1),
        ("Masked Amerigroup_1", 2),
    )
    assert sum(end for _, end in SAMPLES) == 6


def test_reference_scoring_uses_page_ranges_and_does_not_double_count_table_text():
    reference = {"markdown": "other page <td>A &amp; B</td>", "structure": {"children": [
        {"grounding": {"page": 1, "range": {"start": 0, "end": 10}}},
        {"grounding": {"page": 2, "range": {"start": 11, "end": 27}}},
    ]}}
    page = ParsePage(page=2, width_px=100, height_px=100, blocks=[
        ParseBlock(id="b", type="table", text="A & B repeated", table=[["A", "B"]],
                   bbox=BBox(page=2, xyxy=(0, 0, 1, 1)), conf=None)
    ])
    score = score_page(page, reference)
    assert score["reference_token_f1"] == 1
    assert score["invalid_boxes"] == 0
    assert plain_text("<td>A &amp; B</td>") == "A & B"
    page.blocks[0].table = [["A", "B", "B"], ["A"]]
    score = score_page(page, reference)
    assert score["reference_token_precision"] == 0.5
    assert score["ragged_tables"] == 1


@pytest.mark.parametrize("all_filtered", [False, True])
def test_corrective_run_skips_filtered_pages_before_rendering(tmp_path, monkeypatch, all_filtered):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "parse-page.md").write_text("page {page_number}", encoding="utf-8")
    previous = tmp_path / "previous.json"
    filtered = [(name, page) for name, end in (SAMPLES if all_filtered else SAMPLES[:1]) for page in range(1, end + 1)]
    previous.write_text(json.dumps({"pages": [
        {"document": name, "page": page, "status": "content_filtered"} for name, page in filtered
    ]}), encoding="utf-8")
    calls = []

    def preprocess(path, *, start_page, end_page):
        calls.append((path.stem, start_page, end_page))
        return [{"page": p, "base64": "", "doc_sha256": "test"} for p in range(start_page, end_page + 1)]

    references = tmp_path / "references"
    references.mkdir()
    for name, _ in SAMPLES:
        (references / f"{name}.parse.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(evaluation, "REFERENCES", references)
    monkeypatch.setattr(evaluation, "preprocess_pages", preprocess)
    monkeypatch.setattr(evaluation, "_build_llm", lambda: SimpleNamespace(reasoning_effort="medium"))
    monkeypatch.setattr(evaluation, "run_page", lambda p, prompt: {"page": p["page"], "status": "content_filtered"})
    monkeypatch.setattr(sys, "argv", ["evaluate", "--prompts", str(prompts), "--output", str(tmp_path / "out"),
                                    "--live", "--skip-filtered-from", str(previous)])
    evaluation.main()
    assert calls == ([] if all_filtered else [(name, 1, end) for name, end in SAMPLES[1:]])
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["pages"]) == (0 if all_filtered else 5)
    assert manifest["skipped_content_filtered"] == [list(item) for item in sorted(filtered)]
