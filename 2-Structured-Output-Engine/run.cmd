@echo off
setlocal
REM Structured Output Engine - Windows launcher.
REM Native Windows only: plain python + pip + venv, no WSL2, no Docker.
REM (Development in this repo uses uv; this script targets an end-user
REM machine that may only have python.org's python + pip installed.)

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not installed or not on PATH. Install it from https://python.org.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create .venv.
        exit /b 1
    )
)

set "VENV_PY=.venv\Scripts\python.exe"

echo Installing dependencies...
"%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies from requirements.txt.
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" (
        echo Creating .env from .env.example - fill in the API keys you plan to use.
        copy /y ".env.example" ".env" >nul
    )
)

echo Checking Ollama...
"%VENV_PY%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/api/version', timeout=2)" >nul 2>&1
if errorlevel 1 (
    echo WARNING: Ollama not reachable at http://127.0.0.1:11434.
    echo          The local provider and default repair model need it running.
    echo          Cloud providers ^(Agnes / OpenAI-compatible / Gemini^) will still
    echo          work if you've set their API keys in .env - continuing.
) else (
    echo Ollama is reachable.
)

echo.
echo Starting the app...
"%VENV_PY%" -m streamlit run src\ui\app.py
