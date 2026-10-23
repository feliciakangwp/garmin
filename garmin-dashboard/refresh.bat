@echo off
cd /d "%~dp0"
python pull.py && python build.py && start "" dashboard.html
