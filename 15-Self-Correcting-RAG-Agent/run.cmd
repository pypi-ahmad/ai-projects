@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === Self-Correcting RAG Agent launcher ===

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
        echo OLLAMA_HOST=http://127.0.0.1:11434
        echo AGNESAI_API_KEY=
        echo OPENAI_API_KEY=
        echo OPENAI_BASE_URL=
        echo GOOGLE_API_KEY=
        echo SEARCH_API_KEY=
        echo SEARCH_BASE_URL=
    ) > ".env.example"
)

if not exist ".env" (
    echo No .env found -- copying .env.example. Edit .env to add your API keys.
    copy /y ".env.example" ".env" >nul
)

echo Checking Ollama is reachable...
ollama list >nul 2>nul
if errorlevel 1 (
    echo WARNING: could not reach Ollama ^(ollama list failed^). This agent REQUIRES Ollama
    echo for the demo -- rewrite, critique, answer generation, and embedding all run locally
    echo through it. Install/start Ollama and pull the models listed in SPEC.md's allowlist,
    echo then re-run this launcher.
) else (
    echo Ollama is reachable.
)

if not exist "data\indexes\qdrant" (
    echo No index found -- indexing the seeded demo wiki ^(data\raw\wiki^)...
    ".venv\Scripts\python.exe" -m self_correcting_rag.index --input data\raw\wiki --index data\indexes
)

echo Starting Streamlit...
".venv\Scripts\python.exe" -m streamlit run src\self_correcting_rag\ui\app.py

endlocal
