<p align="center">
  <img src="assets/icon-256.png" width="128" alt="Anchor icon">
</p>

<h1 align="center">Anchor</h1>

<p align="center">
  <em>A GUI-driven incremental backup tool for Windows 10 and 11.</em>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Hans-Tandt/Anchor" alt="License: MIT"></a>
  <a href="https://github.com/Hans-Tandt/Anchor/releases"><img src="https://img.shields.io/github/v/release/Hans-Tandt/Anchor?include_prereleases" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-blue" alt="Windows 10 / 11">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
</p>

---

## What it does

Anchor makes an incremental copy of the folders you choose to any place you can write to — a USB drive, a network share, your OneDrive folder, or a remote NAS over SFTP or WebDAV. It only copies what has actually changed since the last run, keeps optional older versions of each file so a bad edit can be rolled back, and confirms after every run that everything you wanted is really at the destination.

Set it up once, schedule it, and forget it. Or run it by hand from a friendly GUI.

## Features

| Area | What you get |
|---|---|
| **Destinations** | Local drives, USB, UNC network shares, OneDrive folders (any local path really), SFTP, WebDAV |
| **Incremental** | Detects changes by size + modification time (fast) or SHA-256 hash (paranoid) |
| **Safe writes** | Every file is written to a `.tmp` sibling then atomically renamed; local writes also `fsync` before rename |
| **Versioning** | Keep up to N previous versions of each file under `_anchor_versions/` — protects against ransomware and bad edits |
| **Restore UI** | Browse the destination tree, pick a file and a version, restore to the original location or an alternate folder |
| **Post-copy verify** | After copy, Anchor re-walks your source and checks every file is at the destination with the right size — proves the backup actually worked |
| **Mirror-delete** | Optionally delete files at the destination that vanished from the source, with a safety cap that refuses to remove more than X% of known files in one run |
| **Group runs** | Ctrl-click multiple profiles, click "Run selected", they run one after another |
| **Multi-destination** | One profile can back up to several destinations at once |
| **Scheduling** | Native Windows Task Scheduler integration — daily, weekly, on sign-in |
| **Credentials** | Remote passwords stored in Windows Credential Manager, never on disk in plain text |
| **Long paths** | Automatically uses `\\?\` prefix so files past 260 characters don't silently fail |
| **Parallel** | Local copies use a configurable thread pool; remote copies stay serial (one channel) |
| **Diagnostic tool** | `diagnose.py` prints paths, state, and can explain what the engine would do for any single file |

## Download

Grab the latest release from the [Releases page](https://github.com/Hans-Tandt/Anchor/releases/latest).

Because the download is not code-signed, Windows SmartScreen will show a blue warning when you first run it. Click **More info** → **Run anyway**. If that makes you uncomfortable, run from source instead (see below).

## Run from source

Anchor needs Python 3.10 or newer.

1. Install Python from <https://www.python.org/downloads/windows/> (tick *Add Python to PATH* during install).
2. Clone or download this repo, then open a terminal in the folder.
3. Install the dependencies:
   ```bat
   install.bat
   ```
   Or the manual equivalent:
   ```bat
   python -m pip install -r requirements.txt
   ```
4. Launch the GUI:
   ```bat
   run.bat
   ```
   Or:
   ```bat
   python -m anchor
   ```

That's it. Create a profile from the GUI, add sources and a destination, and click **Run backup now**.

## Build the .exe

Anchor ships a `build.bat` that produces a standalone Windows build via PyInstaller. From the project root:

```bat
build.bat
```

The first run auto-installs PyInstaller (~50 MB) if it isn't present. Subsequent builds skip that step.

Output layout:

```
dist\Anchor\
├── Anchor.exe          <-- launch this
└── _internal\          <-- Qt libraries, Python runtime, bundled data
                            (must stay next to Anchor.exe)
```

To share the build, zip the whole `dist\Anchor\` folder. The exe on its own won't run — it needs `_internal\` beside it.

The bundled exe also acts as the CLI dispatcher for scheduled backups: `Anchor.exe --cli --profile <id> --silent`. Anchor's scheduler auto-detects the frozen build and writes tasks against the exe instead of `python -m anchor.cli`.

A future release will wrap this into a signed Inno Setup installer. For now, the zip works fine on any Windows 10/11 machine without Python installed.

## Project structure

| Path | What lives there |
|---|---|
| `anchor/` | The Python package (engine, destinations, GUI, CLI) |
| `anchor/core/` | Engine, walker, state DB, run lock, backup profile model |
| `anchor/destinations/` | Adapters: local, SFTP, WebDAV — all speak one `Destination` interface |
| `anchor/gui/` | PySide6 dialogs and main window |
| `anchor/TechEase/` | Bundled brand assets (sidebar footer) |
| `assets/` | App icon (`icon.ico`) and PNG previews |
| `scripts/` | Build-time tools (currently: `make_icon.py`) |
| `logs/` | Rotating monthly log files, created on first run |
| `diagnose.py` | Standalone diagnostic tool |
| `install.bat` / `run.bat` | Windows launchers |

Runtime user data (profiles, state DBs, credentials) lives under `%APPDATA%\Anchor\` — Anchor never writes those into the repo folder.

## Contributing

Bug reports, feature ideas, and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first — it's short.

Please also read the [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Found a security issue? Please **do not** open a public issue. See [SECURITY.md](SECURITY.md) for how to report it privately.

## Licence

[MIT](LICENSE) — © 2026 Hans-Tandt.

## Author

**Hans-Tandt** — [GitHub profile](https://github.com/Hans-Tandt)
