@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === Local RAG Pipeline launcher ===

if not exist ".venv" (
    echo Creating .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create .venv. Is Python installed and on PATH?
        exit /b 1
    )
)

echo Installing dependencies from requirements.txt...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo pip install failed. See the error above.
    exit /b 1
)

if not exist ".env.example" (
    echo Writing .env.example...
    (
        echo AGNES_API_KEY=
        echo OPENAI_API_KEY=
        echo OPENAI_BASE_URL=
        echo GOOGLE_API_KEY=
        echo OLLAMA_HOST=http://127.0.0.1:11434
    ) > ".env.example"
)

if not exist ".env" (
    echo No .env found -- copying .env.example. Edit .env to add your API keys.
    copy /y ".env.example" ".env" >nul
)

echo Checking Ollama is reachable...
ollama list >nul 2>nul
if errorlevel 1 (
    echo WARNING: could not reach Ollama ^(ollama list failed^). The Ollama provider,
    echo embedding, OCR, and reranking will not work until Ollama is running.
    echo See docs\RUNBOOK.md for setup.
) else (
    echo Ollama is reachable.
)

echo Starting Streamlit...
".venv\Scripts\python.exe" -m streamlit run src\rag_pipeline\ui\app.py

endlocal
