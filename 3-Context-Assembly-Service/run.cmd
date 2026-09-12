@echo off
cd /d "%~dp0"

:: ── create venv if absent ────────────────────────────────────────────────────
if not exist .venv (
    echo [setup] Creating virtual environment...
    uv venv
)

:: ── install / sync dependencies ──────────────────────────────────────────────
echo [setup] Syncing dependencies...
uv sync --quiet

:: ── load .env if it exists ───────────────────────────────────────────────────
if exist .env (
    echo [setup] Loading .env...
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)

:: ── optional: warn if Ollama unreachable (packing still works offline) ───────
uv run python -c ^
  "import urllib.request, sys; ^
   urllib.request.urlopen('http://localhost:11434/api/tags', timeout=2); ^
   print('[ok] Ollama reachable')" ^
  2>nul || echo [warn] Ollama not reachable -- compression disabled; packing works offline.

:: ── launch Streamlit ─────────────────────────────────────────────────────────
echo [start] Launching Context Assembly Service...
uv run streamlit run src\ui\app.py %*
