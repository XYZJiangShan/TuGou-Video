@echo off
chcp 65001 >nul
title 打包泥鳅工具箱 EXE

echo ====================================
echo   打包泥鳅工具箱 EXE
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
    --name "泥鳅视频工具箱" ^
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
if %errorlevel% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo ====================================
echo   [OK] 打包完成！
echo ====================================
echo.

REM --- 自动复制 ffmpeg/ffprobe ---
set DIST_DIR=dist\泥鳅视频工具箱
if exist "%~dp0ffmpeg.exe" (
    echo 复制 ffmpeg.exe ...
    copy /Y "%~dp0ffmpeg.exe" "%DIST_DIR%\" >nul
) else (
    echo [警告] 未找到 ffmpeg.exe，请手动复制到 %DIST_DIR%\
)

if exist "%~dp0ffprobe.exe" (
    echo 复制 ffprobe.exe ...
    copy /Y "%~dp0ffprobe.exe" "%DIST_DIR%\" >nul
) else (
    echo [警告] 未找到 ffprobe.exe，请手动复制到 %DIST_DIR%\
)

echo.
echo 输出目录: %DIST_DIR%
echo.
pause
