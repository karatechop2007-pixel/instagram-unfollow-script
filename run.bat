@echo off
cd /d "%~dp0"
where python >nul 2>nul || (
  echo Python is not installed. Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist venv (
  echo Setting up (first time only)...
  python -m venv venv
  venv\Scripts\pip install -q -r requirements.txt
)
venv\Scripts\python unfollow.py %*
pause
