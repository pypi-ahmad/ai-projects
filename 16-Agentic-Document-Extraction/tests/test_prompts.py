"""Tests for src.prompts.render_prompt -- template resolution relative to
the installed package (not the caller's cwd), strict placeholder
substitution (a missing key raises KeyError rather than rendering with the
placeholder left in), and that every runtime prompt template in
prompts/runtime/ still renders with its real call-site arguments.

Next: src/prompts.py, or prompts/runtime/*.md for the templates themselves.
"""

import pytest

from src.prompts import render_prompt


def test_prompts_resolve_outside_project_and_preserve_substituted_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    value = '{"text": "café"}\n'
    assert value in render_prompt("markdown-context", markdown_context=value)
    assert "'tax'" in render_prompt("crop-field", field_name="tax", hint="")
    assert render_prompt("parse-page", page_number=2, width_px=800, height_px=600).endswith(
        "This is page 2 (800x600 px)."
    )


def test_prompt_missing_placeholder_fails():
    with pytest.raises(KeyError):
        render_prompt("parse-page")


@pytest.mark.parametrize("name,values", [
    ("parse-page", {"page_number": 2, "width_px": 800, "height_px": 600}),
    ("extract-invoice", {}),
    ("markdown-context", {"markdown_context": '{"text": "café"}\n'}),
    ("validation-feedback", {"feedback": '{"expected": "not evidence"}\n'}),
    ("extract-regions", {"error_summary": 'value {unknown}'}),
    ("crop-line-item", {"hint": 'value {unknown}'}),
    ("crop-field", {"field_name": "tax", "hint": 'value {unknown}'}),
])
def test_all_runtime_templates_render_without_reformatting_data(name, values):
    rendered = render_prompt(name, **values)
    assert rendered.strip()
    for value in values.values():
        assert str(value) in rendered
