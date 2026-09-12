@echo off
REM Semantic Cache Layer -- native Windows launcher. No WSL2, no Docker.
setlocal

cd /d "%~dp0"

echo Checking Ollama is reachable (embeddings are required)...
curl -s -m 3 -o nul -w "%%{http_code}" http://localhost:11434/api/version > "%TEMP%\ollama_check.txt" 2>nul
set /p OLLAMA_STATUS=<"%TEMP%\ollama_check.txt"
del "%TEMP%\ollama_check.txt" >nul 2>&1
if not "%OLLAMA_STATUS%"=="200" (
    echo.
    echo ERROR: Ollama is not reachable at http://localhost:11434
    echo The Semantic Cache Layer requires Ollama for embeddings ^(docs\RUNBOOK.md^).
    echo Start Ollama, then re-run this script.
    exit /b 1
)
echo Ollama is up.

if not exist ".venv" (
    echo Creating virtual environment...
    uv venv .venv
    if errorlevel 1 exit /b 1
)

echo Installing dependencies...
uv pip install -r requirements.txt
if errorlevel 1 exit /b 1

if not exist ".env" (
    echo Creating .env from .env.example...
    copy /y ".env.example" ".env" >nul
)

echo Starting Streamlit...
uv run streamlit run src\ui\app.py
