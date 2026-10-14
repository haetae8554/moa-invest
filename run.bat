@echo off
cd /d "%~dp0"
echo Open the Moa extension in Chrome, then choose Side panel.
python -m order_ui.server %*
if errorlevel 1 pause
