@echo off
REM Build Anchor.exe using PyInstaller.
REM Output: dist\Anchor\Anchor.exe (with dist\Anchor\_internal\ beside it).
REM Requires: pip install pyinstaller (installed automatically on first run).

setlocal
cd /d "%~dp0"

REM Use the Python launcher `py` instead of `python` so we never hit the
REM Microsoft Store `python` redirector sitting at the top of PATH on Win 10/11.
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

echo === Checking PyInstaller ===
%PY% -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed. Installing now...
    %PY% -m pip install --upgrade pip
    %PY% -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo === ERROR ===
        echo Failed to install PyInstaller.
        echo.
        pause
        exit /b 1
    )
)

echo.
echo === Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo === Building Anchor.exe ===
%PY% -m PyInstaller --noconfirm Anchor.spec
if errorlevel 1 (
    echo.
    echo === BUILD FAILED ===
    echo See the PyInstaller output above.
    echo.
    pause
    exit /b 1
)

echo.
echo === Build complete ===
echo Executable: dist\Anchor\Anchor.exe
echo Support:    dist\Anchor\_internal\  (must stay beside the exe)
echo.
echo To distribute: zip the entire dist\Anchor\ folder.
echo.
pause
endlocal
