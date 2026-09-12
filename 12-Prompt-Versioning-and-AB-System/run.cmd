@echo off
REM Plain venv + pip setup (no uv required), then starts the API and the
REM Streamlit UI together. Re-run anytime; steps are idempotent.

if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

REM uv-created venvs skip pip; harmless no-op if it's already there.
python -m ensurepip --upgrade >nul 2>&1

pip install -r requirements.txt

start "promptreg-api" cmd /c python -m promptreg.api
python -m streamlit run src\promptreg\ui\app.py
