@echo off
cd /d "%~dp0"
python -m order_ui.server --open
if errorlevel 1 pause
