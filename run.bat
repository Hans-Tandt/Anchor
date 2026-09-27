@echo off
REM Launches the GUI. Double-click this file to start.
setlocal
cd /d "%~dp0"
where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pythonw -m anchor
) else (
    python -m anchor
)
endlocal
