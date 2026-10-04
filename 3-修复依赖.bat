@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Create the environment first: py -3.14 -m venv .venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. See the output above.
    pause
    exit /b 1
)
echo Python dependencies are ready. See README.md for the native DLL build.
pause
