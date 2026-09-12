@echo off
rem Sets up the environment, then starts the API and the Streamlit UI, each in
rem its own window. Uses `uv sync` (creates the venv + installs deps in one
rem step) rather than a separate venv/pip pair -- this project uses uv
rem exclusively; see docs/phase-6-http-and-ui.md for why.

uv sync --group dev

start "Guardrails API" cmd /k "uv run uvicorn guardrails.api:app --host 127.0.0.1 --port 8000"
start "Guardrails UI" cmd /k "uv run streamlit run src/guardrails/ui.py"
