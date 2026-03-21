@echo off
chcp 65001 >nul
echo ========================================
echo   adb 批量设备安装工具 - 打包成 EXE
echo   https://github.com/gelube/adb-multiinstapp
echo ========================================
echo.

echo [1/3] 检查 PyInstaller...
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo 安装 PyInstaller...
    pip install pyinstaller
)

echo.
echo [2/3] 清理旧的打包文件...
if exist build rmdir /q /s build
if exist dist rmdir /q /s dist
if exist adb_manager.spec del /q adb_manager.spec
echo 清理完成

echo.
echo [3/3] 开始打包...
echo 这可能需要 1-2 分钟，请耐心等待...
echo.

pyinstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --name "adb-multiinstapp" ^
    --distpath "dist" ^
    --workpath "build" ^
    --specpath "." ^
    adb-multiinstapp.py

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   打包成功!
    echo ========================================
    echo.
    echo EXE 文件位置：dist\adb-multiinstapp.exe
    echo.
    dir dist\adb-multiinstapp.exe
    echo.
    echo 提示：可以将 dist\adb-multiinstapp.exe 直接分发给用户
    echo       无需安装 Python 或任何依赖
    echo.
) else (
    echo.
    echo 打包失败！请检查错误信息。
    echo.
)

pause
