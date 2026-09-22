"""AppTest regressions: Sol only, upload identity, and rerun-safe previews."""
import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import graph
from src.diagnostics import PageDiagnostic
from src.schema import ParseResult, ParsePage

APP = Path(__file__).resolve().parents[1] / "src/ui/app.py"


def upload(color="white", pages=1):
    buffer = io.BytesIO()
    image = Image.new("RGB", (100, 100), color)
    image.save(buffer, "PDF", save_all=True, append_images=[image] * (pages - 1))
    return SimpleNamespace(name="same.pdf", getvalue=lambda: buffer.getvalue())


@pytest.fixture
def uploaded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    holder = [upload()]
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: holder[0])
    return holder


@pytest.mark.parametrize("has_diagnostics", [True, False])
def test_failed_run_shows_current_diagnostics_and_excludes_stale_artifacts(uploaded, monkeypatch, has_diagnostics):
    output = Path("data/parse")
    output.mkdir(parents=True)
    (output / "doc.md").write_text("STALE MARKDOWN")
    current = ParseResult(doc_sha="doc", pages=[], page_diagnostics=[
        PageDiagnostic(page=1, outcome="content_filtered", finish_reason="content_filter")])
    monkeypatch.setattr(graph, "run_graph", lambda *a, **k: dict(
        doc_sha="doc", status="parse_failed", parse_error="Page 1 failed", markdown=None,
        parse_result=current if has_diagnostics else None, annotated_pdf_path=None,
        token_usage=[dict(input_tokens=0, output_tokens=0, cached_tokens=0, usage_known=False)]))
    app = AppTest.from_file(str(APP)).run()
    app.button[0].click().run()
    assert not app.exception
    assert not any("STALE MARKDOWN" in item.value for item in app.markdown)
    assert any("exclude unknown usage" in item.value for item in app.caption)
    assert all(item.label.startswith("Reported ") for item in app.metric)
    assert len(app.expander) == int(has_diagnostics)


def test_sol_only_and_tab_reruns_do_not_repeat_calls(uploaded, monkeypatch):
    from src.ui import clipboard
    monkeypatch.setattr(clipboard, "copy_buttons", lambda **kwargs: None)
    calls = []
    current = ParseResult(doc_sha="current", pages=[ParsePage(page=1, width_px=100, height_px=100, blocks=[])])

    def run(*args, **kwargs):
        calls.append(kwargs["model"])
        kwargs["on_progress"](dict(completed=1, total=1, successful=1, failed=0))
        return dict(status="parsed", model=kwargs["model"], parse_result=current, markdown="CURRENT",
                    token_usage=[dict(model=kwargs["model"], input_tokens=1000,
                                      cached_tokens=0, output_tokens=100, usage_known=True)])

    monkeypatch.setattr(graph, "run_graph", run)
    app = AppTest.from_file(str(APP)).run()
    assert not app.selectbox
    app.button[0].click().run()
    assert len(app.get("progress")) == 1
    assert not app.get("iframe")
    for tab in ("Formatted preview", "Parse JSON", "Annotated PDF", "Markdown preview"):
        app.session_state["preview_tab"] = tab
        app.run()
        assert not app.exception
    assert calls == ["gpt-6-sol"]
    assert len(app.session_state["session_token_usage"]) == 1


def test_same_name_new_bytes_reset_count_and_result(uploaded, monkeypatch):
    monkeypatch.setattr(graph, "run_graph", lambda *a, **k: dict(status="parsed", token_usage=[]))
    app = AppTest.from_file(str(APP)).run()
    first_id = app.session_state["upload_id"]
    app.button[0].click().run()
    assert app.subheader
    uploaded[0] = upload("red", pages=2)
    app.run()
    assert not app.exception and not app.subheader
    assert app.session_state["upload_id"] != first_id
    assert app.session_state["detected_total_pages"] == 2
    assert app.session_state["start_page_input"] == 1
    assert app.session_state["end_page_input"] == 2
    assert len(list(Path("data/inbox").glob("*.pdf"))) == 2


def test_bad_upload_and_invalid_range_make_no_calls(uploaded, monkeypatch):
    monkeypatch.setattr(graph, "run_graph", lambda *a, **k: pytest.fail("Unexpected paid call"))
    app = AppTest.from_file(str(APP)).run()
    app.number_input[0].set_value(2).run()
    assert app.button[0].disabled and app.error
    uploaded[0] = SimpleNamespace(name="broken.pdf", getvalue=lambda: b"not a PDF")
    app.run()
    assert not app.exception and app.error and not app.button


def test_migration_resets_legacy_ledger_without_repricing(uploaded):
    app = AppTest.from_file(str(APP))
    app.session_state["session_token_usage"] = [dict(model="legacy-model")]
    app.session_state["last_parse_result"] = dict(status="old")
    app.run()
    assert not app.exception and not app.subheader
    assert app.session_state["session_token_usage"] == []
    assert any("not been repriced" in item.value for item in app.info)
