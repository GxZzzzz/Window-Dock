@echo off
cd /d "%~dp0"
if exist "%~dp0dist\WindowDock\WindowDock.exe" (
    start "Window Dock" "%~dp0dist\WindowDock\WindowDock.exe"
    exit /b
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "Window Dock" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0dock.py"
    exit /b
)
echo Run: python -m pip install -r requirements.txt
echo Then: python dock.py
pause
