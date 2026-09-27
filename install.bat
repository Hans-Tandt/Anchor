@echo off
REM One-time setup: installs Python dependencies.
setlocal
cd /d "%~dp0"
echo Installing dependencies into your current Python environment...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Done. Double-click run.bat to start the app.
pause
endlocal
