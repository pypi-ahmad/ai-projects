@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
if not exist outputs mkdir outputs
REM Training only. Does not start the Streamlit UI.
REM Tees output to outputs\train.log so the UI's live log tail has something to read.
powershell -NoProfile -Command "python -m src.train.run --config configs\train.yaml %* 2>&1 | Tee-Object -FilePath outputs\train.log"
