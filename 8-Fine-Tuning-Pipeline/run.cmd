@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
REM UI only. Does not train — see train.cmd.
streamlit run src\ui\app.py
