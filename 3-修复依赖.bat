@echo off
chcp 936 >nul
title 修复大肥鱼dock栏依赖
echo.
echo   正在重新安装界面库 PyQt5，请稍等一分钟...
echo.
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python.exe"
"%PY%" -m pip install -U PyQt5 -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
echo   看到 Successfully installed 就说明修好了。
echo.
pause