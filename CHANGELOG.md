# Changelog

All notable changes to Anchor are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/).

## [1.4.1] — 2026-11-11

Feedback-driven polish of the 1.4.0 progress UI, plus a theme fix.

### Added
- **Sources / Destinations frames are now colour-coded by availability** — green border when every entry exists, red border that blinks (500 ms) when any entry is missing (disconnected USB drive, unmounted share, renamed source). The 5-second destination-freshness poll re-evaluates on each tick, so plugging a drive in or out flips the frame live with no profile re-select.
- **Legend under the scan donut** with live counts: a gold `●  to copy  N,NNN` row and a muted `●  unchanged  N,NNN` row so there is no ambiguity about what the percentage measures. Counts use thousands separators.
- **Phase tooltips** on Scan / Copy / Verify rows explaining what each phase actually does (Scan vs Verify are easy to confuse — Scan looks at the source, Verify looks at the destination).

### Changed
- **Cancel button** now uses the `#danger` style (red border and text) so it's obviously the stop action during a live run, instead of blending in with the other disabled secondary buttons.
- **Disabled primary and danger buttons** actually look disabled now (muted background, dashed border). Previously "Run backup now" kept its gold background while disabled during a run.
- **Scan donut is hidden until scan-done** — its live percentage during classify wobbled wildly as the first few files landed in each bucket, which was more confusing than informative. It now snaps to the resolved ratio at scan-done and stays visible through Copy and Verify.
- **Scan donut is also hidden** in idle, at app launch, and during a standalone Verify run — anywhere it has nothing meaningful to show.

### Fixed
- **Log toggle button** no longer renders as a light-grey Fusion default on the dark theme. Added a `QToolButton` rule to the theme so it matches the other header buttons and themes cleanly across a Toggle-theme cycle.

## [1.4.0] — 2026-11-11

New exclusions UI and new progress UI. Also fixes `run.bat` and hardens `build.bat` so the two script-level traps that caused recent confusion can't bite again silently.

### Added
- **Exclusions tab is now a preset grid** of 26 common patterns grouped into *System junk*, *Build and cache folders*, *IDE metadata*, and *Version control (⚠ dangerous)*. Each preset has a tooltip. The red VCS warning banner also fires from the new folder-exclusions list.
- **Specific folders to skip (absolute paths)** — dedicated list below the preset grid, backed by `BackupProfile.exclude_dirs`. Covers the "don't back up this one specific folder" case cleanly.
- **Custom patterns** — compact textarea kept for globs no preset covers.
- **Multi-phase progress UI** — Scan / Copy / Verify each get their own mini bar, state icon and duration, plus an overall weighted bar (scan 10 / copy 80 / verify 10). A live 72×72 donut on the right fills as the scan phase classifies files, showing the "to copy" vs "unchanged" ratio in real time.
- **Confirm before copy** — new per-profile option *Wait for me to confirm before copying*. When on, the engine pauses at the end of the scan phase and the GUI shows a *Start copy — N files, M MB* button instead of auto-proceeding. Cancel still works.
- **Verify banner** — green auto-dismissing *Verify PASSED* after a passing verify run; red sticky click-to-open-issues *Verify FAILED* banner on fail.
- **Collapsible log card** on the main window; collapsed state persists in `settings.json` (`log_collapsed`).

### Changed
- Default `exclude_globs` now holds only file globs (`*.tmp`, `*.log`, `~$*`, `Thumbs.db`, `.DS_Store`); dir basenames (`node_modules`, `__pycache__`, `.venv`) move to the new default `exclude_dirs`. Old profiles with dir basenames in `exclude_globs` still work and are silently migrated on save.
- Start-of-run VCS WARN now checks both `exclude_globs` and `exclude_dirs` (plus absolute paths ending in a VCS basename), so ticking the new `.git` preset still produces the warning.
- `run.bat` prefers the `pyw` launcher (no console window) with `py` fallback. Removes the old `pythonw / python` probe that silently fell through to the Microsoft Store Python redirect on fresh Windows machines.
- `build.bat` verifies that `rmdir /s /q build` and `rmdir /s /q dist` actually removed the folders (silent failure when a file is in use — typically the previously built `Anchor.exe` — was previously invisible). Also verifies the exe ends up at `dist\Anchor\Anchor.exe` before claiming success.

## [1.3.0] — 2026-11-11

Data-safety fix: Git history was being silently skipped.

### Fixed
- **`.git` is no longer in the default exclusion list** for new profiles. Previous defaults excluded `.git`, so Anchor was skipping the entire version-control history (commits, branches, tags) of every repository under the sources — a real data-loss trap. Several local repos had histories that never reached the destination.
- Existing profiles that already have `.git` in their saved exclusion list are left alone (not silently rewritten), but:
  - The Exclusions tab now shows a red ⚠ warning when any version-control folder (`.git`, `.svn`, `.hg`, `.bzr`) is listed, explaining what will be lost.
  - The engine logs a WARN line at the start of every run with `.git` excluded.
- Open each existing profile → Edit → Exclusions → remove the `.git` line to protect its Git history going forward.

### Changed
- Default `exclude_globs` reduced to: `*.tmp`, `*.log`, `~$*`, `Thumbs.db`, `.DS_Store`, `node_modules`, `__pycache__`, `.venv`.

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
