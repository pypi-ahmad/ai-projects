"""Not a pipeline component -- this package is empty and unused by any of the
harness's code. It exists only because the `uv_build` backend (see
pyproject.toml) maps the project name `llm-eval-harness` to an importable
package of that name. All real code lives in the flat `src/<module>` packages
(dataset, providers, runners, metrics, judge, eval, gate, ui) -- see
docs/ARCHITECTURE.md.
"""
