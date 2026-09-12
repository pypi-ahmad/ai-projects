# Phase 6; Streamlit UI and run.cmd

**Implement** `src/ui/app.py` and the real `run.cmd`.

**UI:**
- Sidebar: `max_retries`.
- Upload to `data/inbox`, then a **Run graph** action.
- Show status, the `Invoice` JSON, the `ValidationReport`, `retry_count`, and any crop thumbnails.
- A review queue sourced from `data/review`, letting the reviewer edit fields, **Re-validate** (Python only, no model call), **Accept override** (requires a reviewer name; sets `human_override=true`; writes to committed + an audit line), or **Retry extract**.

**`run.cmd`:**
```bat
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
python -m streamlit run src/ui/app.py
```

**README:** add a 30-second path; generate the fixture PNG, set the API key, run `run.cmd`, upload the fixture.

Stop after this phase.
