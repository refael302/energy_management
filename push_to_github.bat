@echo off
chcp 65001 >nul
cd /d "%~dp0"

git add .
git status

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0commit-msg.ps1"
if errorlevel 1 (
    echo.
    echo Commit skipped or failed — push not run.
    pause
    exit /b 1
)

echo.
git push origin main
pause
