@echo off
chcp 65001 >nul
title 土狗管理员总管理工具
echo ===================================
echo   🐶 土狗管理员总管理工具
echo ===================================
echo.

:: 寻找 Python
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=py -3
    echo 使用 Python: py -3
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set PYTHON_CMD=python
        echo 使用 Python: python
    ) else (
        echo [错误] 未找到 Python，请安装 Python 3.8+
        pause
        exit /b 1
    )
)

echo 启动总管理工具...
%PYTHON_CMD% "%~dp0super_admin_tool.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] 启动失败，错误码: %ERRORLEVEL%
    pause
)
