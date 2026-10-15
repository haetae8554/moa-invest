@echo off
cd /d "%~dp0"
python scripts\install_native_host.py
if errorlevel 1 (
  echo Setup failed. Install Python 3.11+ and try again.
) else (
  echo Reload the Moa extension in chrome://extensions.
)
pause
