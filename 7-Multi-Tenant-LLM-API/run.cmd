@echo off
setlocal enabledelayedexpansion

REM Ensures .venv + locked dependencies exist. This project uses uv, not
REM pip, throughout (pyproject.toml / uv.lock) -- `uv sync` is this
REM project's equivalent of the phase spec's "venv, pip" step.
uv sync --quiet

REM Load .env into the environment if present (git-ignored -- see
REM .gitignore -- so this is a no-op on a machine without one).
if exist .env (
  for /f "usebackq delims=" %%L in (`findstr /v "^#" .env`) do (
    set "line=%%L"
    if not "!line!"=="" (
      for /f "tokens=1,* delims==" %%A in ("!line!") do set "%%A=%%B"
    )
  )
)

if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=8000
if "%ADMIN_UI_PORT%"=="" set ADMIN_UI_PORT=7011

REM Real module is src.api.app:app (src/api/app.py) -- there is no
REM src/api/main.py.
start "api" uv run uvicorn src.api.app:app --host %HOST% --port %PORT%
start "admin" uv run streamlit run src\ui\app.py --server.port %ADMIN_UI_PORT%
