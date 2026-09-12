@echo off
REM Phase 6: sets up the venv, installs deps, and starts the API + Streamlit
REM UI as two separate windows. Native Windows 11, no WSL2, no Docker.

setlocal
cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    uv venv --python 3.13.15 .venv
    if errorlevel 1 goto :error
)

echo Installing dependencies...
uv pip install --python .venv -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Starting API on http://127.0.0.1:8765 ...
start "Tool-Calling API" cmd /k "uv run --python .venv python -m uvicorn src.tools.api:app --host 127.0.0.1 --port 8765"

echo Starting Streamlit UI on http://127.0.0.1:7018 ...
start "Tool-Calling UI" cmd /k "uv run --python .venv streamlit run src\tools\ui.py"

echo.
echo API:       http://127.0.0.1:8765
echo Streamlit: http://127.0.0.1:7018 (port set in .streamlit\config.toml)
echo Both are running in their own windows -- close those windows to stop them.
goto :eof

:error
echo Setup failed -- see the error above.
exit /b 1
