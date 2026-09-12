"""Render a prompt body against caller-supplied variables.

`str.format_map` (stdlib) only ever does attribute/item lookups on the
values you give it — never `eval`/`exec` — so no `variables` value can
make it run arbitrary Python. That's what "do not execute arbitrary
Python in templates" means here; Jinja2 wasn't added for it.
"""

from __future__ import annotations

from typing import Any


class TemplateRenderError(Exception):
    """A required template variable was not supplied."""


def render(template: str, variables: dict[str, Any]) -> str:
    try:
        return template.format_map(variables)
    except KeyError as exc:
        name = exc.args[0] if exc.args else "?"
        msg = f"missing template variable: {name}"
        raise TemplateRenderError(msg) from exc
