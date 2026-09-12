# Runbook

## Start / stop

Start both the API and the UI: `run.cmd`, or separately:

```
uv run python -m promptreg.api
uv run streamlit run src/promptreg/ui/app.py
```

Stop either with Ctrl-C in its terminal (both are plain foreground
processes; there is no daemon/service wrapper, no PID file). `run.cmd`
launches the API in a separate `cmd` window (`start "promptreg-api" ...`)
and the UI in the current one — closing a window stops that process.

There is no health-check endpoint; confirm the API is up with
`GET /v1/prompts/<any-name>/versions` (200, possibly an empty list) or
watch its stdout for `Uvicorn running on http://127.0.0.1:8000`.

## Logs

There is no log file and no `logging` module usage anywhere in
`src/promptreg/`. Diagnostics are whatever `print()` calls produce (the
generated admin-token line at API startup, the CLI's own output) plus
`uvicorn`'s and `streamlit`'s own console output — all to the terminal
that started the process, nothing written to disk beyond `data/`.

## Troubleshooting by error string

| You see | Where it's raised | What it means |
|---|---|---|
| `INTEGRITY: sha256 mismatch for ...` (`IntegrityError`) | `Registry.get` | the body file on disk no longer matches the hash stored at publish time — something edited or corrupted a file under `data/prompts/` outside of `publish` |
| `no version N for prompt 'X'` (`KeyError`) | `Registry.get`/`set_pointer`, `ExperimentStore.create_experiment` | that version number doesn't exist for that prompt — check `Registry.list_versions(name)` |
| `no previous pointer for 'X'/env` (`ValueError`) | `Registry.rollback` | the pointer for that `(prompt, env)` was only ever set once — nothing to roll back to yet |
| `prompt 'X' already has a running experiment` (`ValueError`) | `ExperimentStore.set_status` | only one `running` experiment per prompt is allowed (a SQLite partial unique index enforces this); stop the current one first |
| `arm weights must sum to 100, got N` / `arm names must be unique` / `experiment needs at least one arm` (`ValueError`) | `split/models.py` `validate_arms` | the `arms` list passed to `create_experiment` failed validation |
| `missing template variable: X` (`TemplateRenderError`) | `execute/render.py` `render` | `/v1/complete`'s `variables` didn't include a key the prompt body's `{X}` placeholder needs |
| `missing or invalid X-Admin-Token` (HTTP 401) | `api/app.py` `require_admin_token` | wrong or absent header on a write route — check the token printed at API startup, or `$PROMPTREG_ADMIN_TOKEN` if you set one |

`KeyError` -> HTTP 404, `ValueError` -> HTTP 400, `IntegrityError` -> HTTP
500, `TemplateRenderError` -> HTTP 400 (`api/app.py`'s
`@app.exception_handler` mapping — see `docs/ARCHITECTURE.md`).

## Rollback

Implemented (`src/promptreg/registry/storage.py`). Three ways to trigger
it: the `Registry` class directly, the HTTP API, or the Streamlit UI.
There is no CLI subcommand for it — `promptreg.registry`'s CLI only has
`resolve` (see [ARCHITECTURE.md](ARCHITECTURE.md)).

## Roll back an env pointer to its previous version

1. Identify the prompt name and env (`prod` or `staging`).
2. Confirm the current state: `Registry.get_pointer(name, env)` for what's
   live now, `Registry.list_versions(name)` to see the full history.
3. Roll back: `Registry.rollback(name, env)`. Moves the pointer to
   whatever it pointed at immediately before its current value — not
   necessarily "one version lower" — and writes a `pointer_history` row
   with `action='rollback'` for audit.
4. Verify: `Registry.get_pointer(name, env)` shows the new (rolled-back)
   version. `Registry.get(name, version)` on both old and new versions
   confirms bodies are untouched — rollback only ever moves the pointer.
5. Raises `ValueError` if there's no prior pointer value to roll back to
   (the pointer was only ever set once for that env).
6. No data is deleted or overwritten by rollback. Every version stays on
   disk and in `versions`; you can move the pointer forward again the same
   way (`set_pointer`), and rolling back twice in a row toggles between the
   last two values.

## Via the HTTP API

```
curl -X POST http://127.0.0.1:8000/v1/prompts/{name}/rollback/{env} \
  -H "X-Admin-Token: $PROMPTREG_ADMIN_TOKEN"
```

No request body. Thin wrapper over `Registry.rollback` — no new logic,
just transport, same `ValueError` (no prior pointer) surfaced as 400.

## Via the Streamlit UI

"Pointer & rollback" tab, per prompt: current pointer for `prod` and
`staging`, a version selector + "Set pointer" button, and a "Roll back"
button next to it — calls the same `Registry.rollback`.
