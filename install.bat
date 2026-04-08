@echo off
chcp 65001 >nul
title 安装依赖

echo ====================================
echo   安装 Python 依赖
echo ====================================
echo.

REM --- 查找 Python ---
set PYTHON=C:\Users\sssjiang\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if exist "%PYTHON%" goto :install

where python >nul 2>nul
if %errorlevel% equ 0 (
    set PYTHON=python
    goto :install
)

echo [错误] 未找到 Python
pause
exit /b 1

:install
echo 使用: 
%PYTHON% --version
echo.
echo 安装中...
%PYTHON% -m pip install -r "%~dp0requirements.txt" --upgrade
echo.

if %errorlevel% equ 0 (
    echo [OK] 依赖安装完成！
) else (
    echo [错误] 安装失败，请检查网络
)

echo.
pause
