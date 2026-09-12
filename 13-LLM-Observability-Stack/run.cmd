@echo off
REM LLM Observability Stack launcher. Native Windows, no WSL2, no Docker.
REM Starts the FastAPI backend and the Streamlit UI, each in its own window.

uv sync --all-groups

start "obs-api" cmd /k uv run python -m obs.api
start "obs-ui" cmd /k uv run streamlit run src\obs\ui\app.py --server.port 7017

echo API: http://127.0.0.1:8000
echo UI:  http://127.0.0.1:7017
echo Two windows opened - close them to stop each service.
