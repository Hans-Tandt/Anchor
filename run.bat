@echo off
REM Launches the Anchor GUI. Double-click this file to start.
REM
REM Uses the `py` launcher (`pyw` when present for a silent, console-free
REM launch) so we never hit the Microsoft Store `python` / `pythonw`
REM redirect sitting at the top of PATH on Windows 10/11, which exits
REM 9009 and opens the Store page.

setlocal
cd /d "%~dp0"

REM Prefer `pyw` (no console window) when available.
where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pyw -m anchor
    goto :done
)

REM Fall back to `py` (opens a console window alongside the GUI).
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -m anchor
    goto :done
)

echo.
echo === ERROR ===
echo Neither `pyw` nor `py` was found on PATH.
echo Install the Python launcher from:
echo   https://www.python.org/downloads/windows/
echo and tick "Add Python to PATH" during install.
echo.
pause
exit /b 1

:done
endlocal
