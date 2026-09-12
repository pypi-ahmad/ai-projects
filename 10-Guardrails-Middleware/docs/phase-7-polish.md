# Phase 7; docs-match-code audit, pinning, polish

## Scope

No new features; confirmed all 88 tests passed before touching anything, then made no behavior
changes. Pure documentation accuracy, packaging, and deployment polish.

## What changed

- **`docs/PII.md`**; removed a stale claim ("no logging call in this codebase yet"); Phase 6
  added `api.py`'s `_log_finding`. Added an explicit false-positive-risk and
  not-a-compliance-certification statement.
- **`docs/THREAT_NOTES.md`**; two claims had gone stale since Phase 4 added real coverage for
  what they said was uncaught: "not homoglyphs" (rewritten; `encoding_evasion` catches fullwidth
  + a small homoglyph set, with limits now stated precisely) and "isn't caught by the outbound
  chain" for leak phrases (rewritten; `blocklist_leak_phrases` catches known phrasings; only
  *different* wording still slips through). Added the same compliance disclaimer as `PII.md`.
- **`docs/API.md`, `docs/DETECTORS.md`, `docs/POLICIES.md`**; checked field names, endpoint
  paths, config defaults, and regex/threshold values against the current source; no drift found,
  left as-is.
- **`README.md`**; a self-contained, ~9-line `wrap_call` example (imports through return),
  replacing the narrower snippet that assumed a `guard` already existed. Added the same
  compliance disclaimer near the top.
- **`requirements.txt`**; was a stub pointing at `uv export`; now the actual pinned output of
  `uv export --no-dev --no-hashes -o requirements.txt` (main dependencies only; pytest/ruff/ty/
  httpx2 stay dev-only). Regenerate the same way after any dependency change.
- **`.streamlit/config.toml`** (new); `[server] port = 7014`, `[theme] base = "dark"`. Verified
  live: started the UI and confirmed it actually served on `:7014` (then stopped it; same
  `taskkill /F /T` process as Phase 6's smoke test, since `kill %1` doesn't reach it on Windows).
  Dark theme is a config value only checkable visually, not by an HTTP status code; not
  independently re-verified beyond confirming the TOML parses (streamlit would have errored on
  malformed config, and didn't).

## What's deliberately unchanged

- No detector logic, config schema, or API/library behavior changed; this phase was scoped to
  documentation and packaging, and the tests already passed going in.
- `detectors.py`'s overlap with `rules.py` and `policies.py`'s unwired `strict`/`observe` names
  remain the same open questions noted since Phase 4/5; not this phase's job to resolve.

## Run it

```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src/
```

All four pass; still 88 tests, unchanged from Phase 6 (no code touched).
