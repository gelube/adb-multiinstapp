@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" "adb_manager.exe"
