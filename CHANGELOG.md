# Changelog

All notable changes to Anchor are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/).

## [1.2.0] — 2026-09-27

First packaged Windows build. Users who don't want to install Python can now grab a runnable bundle directly.

### Added
- `build.bat` and `Anchor.spec` — one-click PyInstaller build producing `dist\Anchor\Anchor.exe` with `_internal\` beside it. Bundles TechEase assets, the app icon, and hidden imports for lazy-loaded SFTP/WebDAV/keyring modules.
- `anchor/__main__.py` now dispatches to the CLI when invoked with `--cli`, so scheduled tasks can run the frozen exe.
- v1.2.0 release ships `Anchor_V1.2.0_Windows.zip` — full runnable bundle with no Python required on the target machine.

### Changed
- `anchor/scheduler.py` detects `sys.frozen` and builds the schtasks command against `Anchor.exe --cli` in a packaged build, `pythonw -m anchor.cli` in a source install.
- Log location: `%APPDATA%\Anchor\logs\` when running as the frozen exe (the install folder may be read-only); still `<project>/logs/` when running from source.

## [1.1.0] — 2026-05-23

Hardening pass on top of the initial release: seven data-safety fixes,
several requested UX changes, and the missing high-value features
(versioning, restore, verify).

### Added
- **Versioning.** New profile setting `keep_versions` (default 0, off). When set, the previous copy of a file is moved into `_anchor_versions/<rel_path>/<file>__<YYYYMMDDTHHMMSS>.bak` before every overwrite or mirror-delete, then pruned to N. Protects against ransomware and bad edits.
- **Restore UI.** Browse a destination tree, pick a file and a version (current or any archived one), restore to the original location or an alternate folder. Runs in a background thread with progress.
- **Post-copy verification phase.** After copy, Anchor re-walks the source and checks every file is at the destination with matching size — proves the backup actually worked. Default on; togglable per profile.
- **Verify action.** Standalone menu item that walks the destination, hashes every file if the profile is in hash-verify mode, and reports mismatches, missing files, and unexpected extras.
- **Multi-profile group runs.** Ctrl/Shift-click profiles in the sidebar, click "Run selected" — they run one after another, each with its own lock.
- **Failed-files panel.** After runs with errors, a "View N issues" button appears with a copy-friendly table and CSV export.
- **Flat destination layout** (per-profile option, single-source only). Files go straight into the destination root instead of a per-source sub-folder.
- **Parallel workers for local destinations.** The unused `parallel_workers` setting now actually parallelises local copies via a thread pool. SFTP and WebDAV stay serial (single-channel).
- **Two- (then four-) phase progress UX.** `scanning → scan-done → copying → verifying → done`, with the bar resetting between phases. Configurable pause between scan and copy.
- **Diagnostic tool.** `python diagnose.py` prints paths, profiles, and state-DB row counts. `python diagnose.py --check <file>` explains exactly what the engine would decide for one specific source file (new / unchanged / would be adopted / excluded).
- **App icon.** Multi-resolution `assets/icon.ico` embedded in the window and taskbar.
- **Open logs / profiles / app folder** buttons in Settings, plus an **Open logs** button in the main window header.
- **Options-tab controls** for `keep_versions`, `mirror_max_delete_pct`, `flat_destination_layout`, and `verify_after_copy`.

### Fixed
- **SFTP atomic overwrite** now uses the `posix-rename@openssh.com` extension when supported, closing a window where the destination file was briefly absent during rename.
- **WebDAV upload** now writes to a `.tmp` sibling and `MOVE`s it into place — a failed upload can no longer corrupt the destination.
- **Local writes fsync** the `.tmp` file (and on POSIX, the parent directory) before renaming, so a power loss can't leave a renamed-but-empty file.
- **Mirror-delete guards.** Refuses to run for a source root that has vanished (unmounted USB), and refuses to delete more than `mirror_max_delete_pct` percent of known files in a single run.
- **Windows long-path handling.** Local destination paths approaching 260 characters get the `\\?\` prefix automatically (UNC form for network shares).
- **Per-profile run lock.** A manual "Run now" while a scheduled task fires no longer races the state DB.
- Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)` to silence Python 3.12+ warnings.
- Fixed a layout bug where a long current-file path in the progress label would resize the whole window.

### Changed
- Logs now live in `<project>/logs/` for discoverability, with a fallback to `%APPDATA%\Anchor\logs\` when the project folder isn't writable.
- The GUI log viewer filters to INFO+ only. Per-file noise (Adopted, Mirrored deletion) still goes to the file log at DEBUG for forensics.
- Progress label is now elided in the middle when it doesn't fit; full text preserved in the tooltip.

## [1.0.0] — 2026-05-18

Initial release.

### Added
- PySide6 GUI: main window with profile sidebar, profile editor with Sources / Destinations / Exclusions / Options tabs, schedule dialog, settings dialog, dark/light theme.
- Incremental engine with per-profile SQLite state DB.
- Destination adapters: Local (drives, USB, UNC, OneDrive folder), SFTP (via paramiko), WebDAV (via webdavclient3).
- Windows Task Scheduler integration via `schtasks.exe`.
- Windows drive enumeration.
- Password storage via Windows Credential Manager (keyring).
- Rotating log files.
