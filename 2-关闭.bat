@echo off
setlocal
cd /d "%~dp0"
if exist "dist\WindowDock\WindowDock.exe" (
    "dist\WindowDock\WindowDock.exe" --stop
    exit /b
)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" dock.py --stop
    exit /b
)
python dock.py --stop
