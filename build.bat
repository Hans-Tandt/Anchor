@echo off
REM Build Anchor.exe using PyInstaller.
REM Output: dist\Anchor\Anchor.exe (with dist\Anchor\_internal\ beside it).
REM Requires: pip install pyinstaller (installed automatically on first run).

setlocal
cd /d "%~dp0"

echo === Checking PyInstaller ===
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed. Installing now...
    python -m pip install --upgrade pip
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo Failed to install PyInstaller. Aborting.
        exit /b 1
    )
)

echo.
echo === Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo === Building Anchor.exe ===
python -m PyInstaller --noconfirm Anchor.spec
if errorlevel 1 (
    echo.
    echo BUILD FAILED. See the PyInstaller output above.
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
