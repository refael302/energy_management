@echo off
cd /d "C:\Dev\energy_management"
git add .
git status
set /p msg="Commit message: "
git commit -m "%msg%"
git push origin main
pause
