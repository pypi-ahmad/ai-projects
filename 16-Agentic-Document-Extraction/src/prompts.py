"""Loads a prompt template from prompts/runtime/<name>.md and fills in its
`{placeholder}` values via `str.format`. A template referencing a value the
caller didn't supply raises `KeyError` rather than rendering with the
placeholder left in (see tests/test_prompts.py) -- callers are expected to
pass every value the template needs, not to handle a partially-filled prompt.

All model-facing instruction text belongs in prompts/runtime/*.md. Callers
may supply document data and page metadata, but must not assemble prompt
instructions in Python.
"""

from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts" / "runtime"


def render_prompt(name: str, **values: object) -> str:
    # Resolved relative to this file's own location, not the caller's cwd, so
    # rendering works the same whether invoked from the repo root, a test's
    # tmp_path (tests monkeypatch.chdir), or anywhere else.
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").rstrip("\r\n").format(**values)
