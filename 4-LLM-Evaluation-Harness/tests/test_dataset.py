import json

import pytest

from src.dataset import Case, DatasetError, load_suite


def _write_jsonl(path, *rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_load_suite_valid(tmp_path):
    _write_jsonl(
        tmp_path / "a.jsonl",
        {"id": "case-1", "suite": "smoke", "input": {"user": "hi"}},
    )

    cases = load_suite(tmp_path)

    assert len(cases) == 1
    assert isinstance(cases[0], Case)
    assert cases[0].id == "case-1"


def test_load_suite_rejects_duplicate_ids(tmp_path):
    _write_jsonl(tmp_path / "a.jsonl", {"id": "dup", "suite": "smoke", "input": {"user": "one"}})
    _write_jsonl(tmp_path / "b.jsonl", {"id": "dup", "suite": "smoke", "input": {"user": "two"}})

    with pytest.raises(DatasetError, match="duplicate case id"):
        load_suite(tmp_path)


def test_load_suite_reports_invalid_case(tmp_path):
    _write_jsonl(
        tmp_path / "a.jsonl",
        {"id": "bad", "suite": "not-a-suite", "input": {"user": "hi"}},
    )

    with pytest.raises(DatasetError):
        load_suite(tmp_path)
