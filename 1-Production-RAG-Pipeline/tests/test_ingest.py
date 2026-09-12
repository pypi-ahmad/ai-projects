import json
from pathlib import Path

from rag_pipeline.ingest import pipeline

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_txt() -> None:
    pages = pipeline.parse_file(FIXTURES / "sample.txt")
    assert len(pages) == 1
    assert pages[0].text.strip() == "hello from a tiny text fixture"
    assert not pages[0].needs_ocr


def test_parse_html_strips_tags() -> None:
    pages = pipeline.parse_file(FIXTURES / "sample.html")
    assert len(pages) == 1
    assert "<" not in pages[0].text
    assert "should not appear" not in pages[0].text
    assert "ignored" not in pages[0].text
    assert "Tiny HTML fixture" in pages[0].text


def test_page_split_pdf() -> None:
    pages = pipeline.parse_file(FIXTURES / "sample.pdf")
    assert len(pages) == 2
    assert pages[0].page == 1
    assert pages[1].page == 2
    assert "first page" in pages[0].text.lower()
    assert "second page" in pages[1].text.lower()
    assert not pages[0].needs_ocr
    assert not pages[1].needs_ocr


def test_hash_skip(tmp_path, monkeypatch) -> None:
    input_dir = tmp_path / "raw"
    out_dir = tmp_path / "processed"
    input_dir.mkdir()
    (input_dir / "sample.txt").write_text("hello world", encoding="utf-8")

    calls: list[Path] = []
    original_parse_file = pipeline.parse_file

    def counting_parse_file(path: Path):
        calls.append(path)
        return original_parse_file(path)

    monkeypatch.setattr(pipeline, "parse_file", counting_parse_file)

    pipeline.run_ingest(input_dir, out_dir)
    assert len(calls) == 1

    pipeline.run_ingest(input_dir, out_dir)
    assert len(calls) == 1  # unchanged hash -> not reparsed

    out_path = out_dir / pipeline.OUTPUT_FILENAME
    records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["path"] == "sample.txt"
    assert records[0]["hash"]

    # Change the content -> hash changes -> must be reparsed.
    (input_dir / "sample.txt").write_text("hello world, edited", encoding="utf-8")
    pipeline.run_ingest(input_dir, out_dir)
    assert len(calls) == 2
