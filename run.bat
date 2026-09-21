@echo off
setlocal
cd /d "%~dp0"
title Instagram unfollow script

rem Find Python. "python --version" fails on the Microsoft Store stub, so this
rem only picks a real install. Falls back to the "py" launcher.
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY goto nopython

if exist "venv\Scripts\python.exe" goto run

echo Setting up, first time only. This takes a minute...
%PY% -m venv venv
if errorlevel 1 goto venvfail
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail

:run
echo.
"venv\Scripts\python.exe" unfollow.py %*
echo.
echo Script finished.
pause
exit /b 0

:nopython
echo Python was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in the installer.
echo If you already installed it, restart your PC and try again.
pause
exit /b 1

:venvfail
echo Could not create the Python environment. See the error above.
pause
exit /b 1

:pipfail
echo Could not install the required packages. See the error above.
pause
exit /b 1
