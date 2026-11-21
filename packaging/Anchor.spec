# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Anchor.

Build with (from the repository root):
    scripts\\build.bat
or equivalently:
    python -m PyInstaller --noconfirm packaging/Anchor.spec

Produces `dist/Anchor/Anchor.exe` alongside `dist/Anchor/_internal/` (Qt
libraries, Python runtime, bundled data). Zip the whole `dist/Anchor/`
folder for distribution — the exe won't run without _internal beside it.
"""
import os
import re

# SPECPATH is injected by PyInstaller: the folder containing this file.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821


def _p(*parts):
    return os.path.join(ROOT, *parts)


with open(_p("anchor", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)

# Windows version resource (file properties → Details tab).
_v = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
VERSION_FILE = _p("build", "version_info.txt")
os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
with open(VERSION_FILE, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_v}, prodvers={_v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Hans Tandt'),
      StringStruct('FileDescription', 'Anchor - incremental backup for Windows'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'Anchor'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'Anchor.exe'),
      StringStruct('ProductName', 'Anchor'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")

# Modules loaded lazily (factory.py / entry points) that static analysis misses.
hiddenimports = [
    "anchor.destinations.sftp",
    "anchor.destinations.webdav",
    "keyring.backends.Windows",
]

a = Analysis(
    [_p("anchor", "__main__.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Runtime resources read via Path(__file__)-relative paths
        # (app icon, sidebar brand logo).
        (_p("anchor", "resources"), "anchor/resources"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules Anchor never uses — keeps the zip ~100 MB smaller.
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
        "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization", "tkinter",
    ],
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
    icon=_p("anchor", "resources", "icons", "anchor.ico"),
    version=VERSION_FILE,
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
