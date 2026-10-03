@echo off
chcp 936 >nul
setlocal
set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
cd /d "%~dp0"
start "" "%PYW%" "%~dp0dock.py"
endlocal