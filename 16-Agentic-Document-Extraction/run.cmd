@echo off
setlocal
cd /d "%~dp0"
set STREAMLIT_PORT=5805
where uv >nul 2>&1
if errorlevel 1 (
    echo uv is required. Install uv, then run this launcher again.
    exit /b 1
)
if not exist .venv\Scripts\python.exe (
    if exist .venv (
        echo Existing .venv has no Python executable. Repair it before launching.
        exit /b 1
    )
    call uv venv .venv
    if errorlevel 1 goto :failed
)
fc /b requirements.txt .venv\requirements-installed.txt >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies from requirements.txt...
    call uv pip install --python .venv\Scripts\python.exe -r requirements.txt
    if errorlevel 1 goto :failed
    copy /y requirements.txt .venv\requirements-installed.txt >nul
    if errorlevel 1 goto :failed
)
for /f "tokens=5" %%p in ('netstat -aon ^| findstr /C:":%STREAMLIT_PORT% " ^| findstr LISTENING') do (
    taskkill /F /PID %%p >nul 2>&1
)
call uv run --no-project --python .venv\Scripts\python.exe -m streamlit run src/ui/app.py --server.port=%STREAMLIT_PORT% --logger.level=info
exit /b %errorlevel%

:failed
echo Setup failed. Streamlit was not started.
exit /b 1
