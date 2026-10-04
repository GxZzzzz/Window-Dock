@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Create the environment and install requirements.txt first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" dock.py
pause
