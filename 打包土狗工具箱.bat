@echo off
chcp 65001 >nul
title 打包土狗工具箱 EXE

echo ====================================
echo   打包土狗工具箱 EXE
echo ====================================
echo.

REM --- 查找 Python ---
set PYTHON=C:\Users\sssjiang\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if exist "%PYTHON%" goto :build

where python >nul 2>nul
if %errorlevel% equ 0 (
    set PYTHON=python
    goto :build
)

echo [错误] 未找到 Python
pause
exit /b 1

:build
echo 使用:
%PYTHON% --version
echo.

REM --- 确保 PyInstaller 已安装 ---
%PYTHON% -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo 安装 PyInstaller...
    %PYTHON% -m pip install pyinstaller -q
    echo.
)

REM --- 打包 ---
echo 开始打包...
echo.

%PYTHON% -m PyInstaller ^
    --name "土狗视频优化工具" ^
    --onedir ^
    --windowed ^
    --icon "assets\icon.ico" ^
    --add-data "assets\icon.ico;assets" ^
    --add-data "assets\icon.png;assets" ^
    --add-data "assets\yemao_confuse_frame.png;assets" ^
    --add-data "core\*.py;core" ^
    --hidden-import "requests" ^
    --hidden-import "cv2" ^
    --hidden-import "numpy" ^
    --hidden-import "PIL" ^
    --noconfirm ^
    --clean ^
    app.py

echo.
if %errorlevel% equ 0 (
    echo ====================================
    echo   [OK] 打包完成！
    echo   输出: dist\土狗视频优化工具\
    echo ====================================
    echo.
    echo [提示] 运行前需要把 ffmpeg.exe 和 ffprobe.exe
    echo        复制到 dist\土狗视频优化工具\ 目录下
) else (
    echo [错误] 打包失败
)

echo.
pause
