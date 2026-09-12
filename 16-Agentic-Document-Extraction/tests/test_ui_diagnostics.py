"""Streamlit `AppTest`-driven tests for src/ui/app.py -- that a failed run's
diagnostics/usage display reflects the *current* result rather than a stale
data/parse/ file already on disk, and that switching the model dropdown
after a run doesn't trigger a new model call (the dropdown only takes effect
on the next Parse click).

Next: src/ui/app.py.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import graph
from src.diagnostics import PageDiagnostic
from src.schema import ParseResult


@pytest.mark.parametrize("has_diagnostics", [True, False])
def test_failed_run_shows_current_diagnostics_and_excludes_stale_artifacts(tmp_path, monkeypatch, has_diagnostics):
    app_path = Path(__file__).resolve().parents[1] / "src/ui/app.py"
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "data/parse"
    output.mkdir(parents=True)
    (output / "doc.md").write_text("STALE MARKDOWN")
    current = ParseResult(doc_sha="doc", pages=[], page_diagnostics=[
        PageDiagnostic(page=1, outcome="content_filtered", finish_reason="content_filter")])
    (output / "doc.json").write_text(current.model_dump_json())
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: SimpleNamespace(name="test.pdf"))
    monkeypatch.setattr(graph, "run_graph", lambda *a, **k: dict(
        doc_sha="doc", status="parse_failed", parse_error="Page 1 failed", markdown=None,
        parse_result=current if has_diagnostics else None, annotated_pdf_path=None,
        token_usage=[dict(input_tokens=0, output_tokens=0, cached_tokens=0, usage_known=False)]))
    app = AppTest.from_file(str(app_path)).run()
    app.button[0].click().run()
    assert not app.exception
    assert not any("STALE MARKDOWN" in item.value for item in app.markdown)
    assert any("exclude unknown usage" in item.value for item in app.caption)
    assert all(item.label.startswith("Reported ") for item in app.metric)
    assert len(app.expander) == int(has_diagnostics)
    if has_diagnostics:
        assert app.expander[0].label == "API diagnostics"
        assert "content_filtered" in app.json[0].value
    else:
        assert not app.json


def test_model_selection_preserves_result_without_new_calls(tmp_path, monkeypatch):
    app_path = Path(__file__).resolve().parents[1] / "src/ui/app.py"
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: SimpleNamespace(name="test.pdf"))

    def run(*args, **kwargs):
        calls.append(kwargs["model"])
        return dict(status="parsed", model=kwargs["model"], parse_result=None,
                    token_usage=[dict(model=kwargs["model"], input_tokens=1000,
                                     cached_tokens=0, output_tokens=100, usage_known=True)])

    monkeypatch.setattr(graph, "run_graph", run)
    app = AppTest.from_file(str(app_path)).run()
    assert app.selectbox[0].value == "gpt-5.6-terra"
    app.button[0].click().run()
    app.selectbox[0].select("gpt-5.6-luna").run()
    assert not app.exception
    assert calls == ["gpt-5.6-terra"]
    assert app.subheader[0].value == "Status: parsed"
    assert len(app.session_state["session_token_usage"]) == 1
    assert any("Result model: gpt-5.6-terra" in c.value for c in app.caption)
    app.button[0].click().run()
    assert calls == ["gpt-5.6-terra", "gpt-5.6-luna"]
    assert len(app.session_state["session_token_usage"]) == 2
