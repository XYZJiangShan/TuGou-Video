@echo off
chcp 65001 >nul
title 土狗视频下载器 V1.0

echo ====================================
echo   土狗视频下载器 V1.0 - 启动中...
echo ====================================
echo.

REM 优先使用WorkBuddy venv中的Python（含已安装的依赖）
set PYTHON=C:\Users\sssjiang\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if exist "%PYTHON%" (
    echo Python: %PYTHON% (venv)
    goto :run
)

REM 回退到WorkBuddy自带的Python
set PYTHON=C:\Users\sssjiang\.workbuddy\binaries\python\versions\3.13.12\python.exe
if exist "%PYTHON%" (
    echo Python: %PYTHON%
    goto :run
)

REM 检查系统Python
where python >nul 2>nul
if %errorlevel% equ 0 (
    set PYTHON=python
    echo Python: system python
    goto :run
)

echo [错误] 未找到Python！
pause
exit /b 1

:run
%PYTHON% --version
echo FFmpeg: %~dp0ffmpeg.exe

echo.
echo 正在启动土狗视频下载器...
echo.

cd /d "%~dp0"
%PYTHON% app.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 程序异常退出，请检查日志
    pause
)
