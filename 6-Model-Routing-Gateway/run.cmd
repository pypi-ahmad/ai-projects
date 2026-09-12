@echo off
setlocal enabledelayedexpansion
:: Model Routing Gateway launcher
:: Creates venv if absent, syncs deps, loads .env, starts Streamlit.

if not exist .venv (
    uv venv
)
uv sync --quiet

:: Load .env (skip comment lines and blank lines)
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "line=%%a"
        if not "!line:~0,1!"=="#" if not "%%a"=="" set "%%a=%%b"
    )
)

:: Warn if Ollama is unreachable (non-fatal — cloud-only still works)
if "%OLLAMA_HOST%"=="" set OLLAMA_HOST=http://localhost:11434
curl -s -o nul -w "%%{http_code}" %OLLAMA_HOST%/api/tags 2>nul | findstr /c:"200" >nul ^
    || echo [WARN] Ollama not reachable at %OLLAMA_HOST% -- local tiers will be skipped

echo [INFO] Starting Streamlit at http://localhost:8501
uv run streamlit run src\ui\app.py --server.headless false --browser.gatherUsageStats false
