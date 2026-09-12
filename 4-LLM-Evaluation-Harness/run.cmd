@echo off
REM Launches the Streamlit UI on a plain venv + pip (no uv required).
setlocal

if not exist .venv (
    echo Creating virtual environment in .venv...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies from requirements.txt...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

if not exist .env (
    echo No .env found -- copy .env.example to .env and fill in any provider keys you plan to use.
)

REM -m ensures the repo root (this directory) is on sys.path, so "from src...
REM import ..." resolves regardless of Streamlit's own script-dir handling.
python -m streamlit run src\ui\app.py
