@echo off
chcp 65001 >nul
title 土狗视频优化工具 V1.0

echo ====================================
echo   土狗视频优化工具 V1.0
echo ====================================
echo.

REM --- 查找 Python ---
REM 1) WorkBuddy venv（含已安装依赖）
set PYTHON=C:\Users\sssjiang\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if exist "%PYTHON%" (
    echo [OK] Python: WorkBuddy venv
    goto :check_deps
)

REM 2) 系统 Python
where python >nul 2>nul
if %errorlevel% equ 0 (
    set PYTHON=python
    echo [OK] Python: system
    goto :check_deps
)

echo [错误] 未找到 Python，请先安装 Python 3.10+
pause
exit /b 1

:check_deps
%PYTHON% --version
echo [OK] FFmpeg: %~dp0ffmpeg.exe
echo.

REM --- 检查依赖 ---
%PYTHON% -c "import requests, cv2, numpy, PIL" 2>nul
if %errorlevel% neq 0 (
    echo [提示] 首次运行，正在安装依赖...
    %PYTHON% -m pip install -r "%~dp0requirements.txt" -q
    echo.
)

REM --- 启动 ---
echo 启动中...
echo.
cd /d "%~dp0"
%PYTHON% app.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 程序异常退出
    pause
)
