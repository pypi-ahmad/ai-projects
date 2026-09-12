@echo off
rem Ensures .venv exists and matches pyproject.toml/uv.lock (uv's equivalent
rem of "create a venv, pip install" -- this project is uv-only, see
rem docs/RUNBOOK.md).
uv sync --all-groups
if errorlevel 1 exit /b 1

echo.
echo Once the server below is up:
echo   Static EventSource demo:  http://127.0.0.1:8000/client.html
echo   Streamlit consumer (separate terminal, this one stays on uvicorn):
echo     uv run streamlit run src/stream/ui.py
echo     -^> http://127.0.0.1:7015, dark theme (port + theme set in .streamlit/config.toml)
echo.

uv run uvicorn stream.api:app --host 127.0.0.1 --port 8000
