@echo off
chcp 65001 >nul
title adb 批量设备安装工具
echo ========================================
echo   adb 批量设备安装工具
echo   https://github.com/gelube/adb-multiinstapp
echo ========================================
echo.
cd /d "%~dp0"
if exist "dist\adb-multiinstapp.exe" (
    start "" "dist\adb-multiinstapp.exe"
) else (
    echo 错误：未找到可执行文件
    echo 请先运行 build_exe.bat 打包程序
    pause
)
