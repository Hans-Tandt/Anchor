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
REM rmdir /s /q is silent on failure (files in use, locked exe). Check both
REM folders are actually gone before carrying on, so PyInstaller never ends
REM up writing into a half-deleted tree or failing to overwrite a live exe.
if exist build (
    rmdir /s /q build
    if exist build (
        echo.
        echo === ERROR ===
        echo Could not remove the old 'build' folder.
        echo A file inside may be in use. Close anything that opened it and try again.
        echo.
        pause
        exit /b 1
    )
)
if exist dist (
    rmdir /s /q dist
    if exist dist (
        echo.
        echo === ERROR ===
        echo Could not remove the old 'dist' folder.
        echo Most likely: Anchor.exe is still running, or Explorer has a window
        echo open inside dist\Anchor\. Close them and run build.bat again.
        echo.
        pause
        exit /b 1
    )
)

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

REM Belt-and-braces: PyInstaller sometimes returns 0 even when the final
REM write step was skipped (e.g. permission issue). Fail loudly if the exe
REM isn't where it should be.
if not exist dist\Anchor\Anchor.exe (
    echo.
    echo === BUILD FAILED ===
    echo PyInstaller reported success but dist\Anchor\Anchor.exe is missing.
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
