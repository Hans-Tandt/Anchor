# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Anchor.

Build with:
    build.bat
or equivalently:
    python -m PyInstaller --noconfirm Anchor.spec

Produces `dist/Anchor/Anchor.exe` alongside `dist/Anchor/_internal/` (Qt
libraries, Python runtime, bundled data). Zip the whole `dist/Anchor/`
folder for distribution — the exe won't run without _internal beside it.
"""

# Modules the app loads lazily (through factory.py or entry-points) that
# PyInstaller's static analysis can miss.
hiddenimports = [
    "anchor.destinations.sftp",     # imported lazily by factory.open_destination
    "anchor.destinations.webdav",   # same
    "keyring.backends.Windows",     # keyring auto-selects backends at runtime
]


a = Analysis(
    ["anchor/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # Runtime resources the app reads via Path(__file__)-relative paths.
        ("anchor/TechEase", "anchor/TechEase"),   # sidebar branding assets
        ("assets/icon.ico", "assets"),            # window / taskbar icon
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Anchor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed GUI — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Anchor",
)
