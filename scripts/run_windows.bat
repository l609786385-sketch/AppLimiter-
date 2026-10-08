@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
start "" ".venv\Scripts\pythonw.exe" "%CD%\main.py"
exit /b 0
:failed
echo AppLimiter setup failed. Install Python 3.12 x64 and check the network connection.
pause
exit /b 1
