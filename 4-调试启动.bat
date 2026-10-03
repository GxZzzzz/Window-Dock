@echo off
chcp 936 >nul
title 大肥鱼dock栏 - 调试模式
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python.exe"
cd /d "%~dp0"
echo.
echo   正在以调试模式启动（关掉本窗口也会关掉 Dock）...
echo.
"%PY%" "%~dp0dock.py"
echo.
echo   已退出。如果上面有红色报错，请截图发给 AI。
echo.
pause