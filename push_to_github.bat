@echo off
cd /d "C:\Dev\energy_management"

git add .
git status

git -c core.editor=notepad commit

git push origin main
pause