@echo off
REM One-time setup: installs Python dependencies.
setlocal
cd /d "%~dp0"

REM Use the `py` launcher so we skip the Microsoft Store `python` redirect.
set PY=py
%PY% --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo === ERROR ===
    echo Python launcher 'py' is not available.
    echo Install Python 3.10 or newer from:
    echo   https://www.python.org/downloads/windows/
    echo and tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

echo Installing dependencies into your current Python environment...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo === ERROR ===
    echo Failed to install dependencies.
    echo.
    pause
    exit /b 1
)
echo.
echo Done. Double-click run.bat to start the app.
pause
endlocal
