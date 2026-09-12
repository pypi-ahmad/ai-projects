"""Internal FastAPI surface, 127.0.0.1 only. See docs/ARCHITECTURE.md and docs/API.md.

No re-export here: the FastAPI instance lives at obs.api.app.app. Re-exporting
it as obs.api.app would shadow the app submodule's own name on this package,
making `import obs.api.app` resolve to the instance instead of the module
(verified - `import a.b.c as x` binds via attribute traversal, not
sys.modules, so a package that rebinds `.c` poisons that name for good).
"""
