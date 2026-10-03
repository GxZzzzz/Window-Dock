@echo off
chcp 936 >nul
setlocal
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python.exe"
"%PY%" "%~dp0dock.py" --stop
timeout /t 2 >nul
endlocal