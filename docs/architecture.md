# Architecture

```
                 ┌──────────────────────────── GUI (PySide6) ────────────────────────────┐
                 │ MainWindow ── NavigationRail ── pages/ (Backups · Activity · Settings)│
                 │      │                        dialogs (profile editor, restore, …)    │
                 │      ▼                                                                │
                 │ RunController ── owns exactly one QThread worker at a time            │
                 └──────┬───────────────────────────────────────────────────────────────┘
                        │ BackupWorker / BackupGroupWorker / VerifyWorker
   scheduled task ──► cli.py
                        ▼
                 core/engine.py  BackupEngine · Verifier
                   │   walker.py  (source walk + exclusions)
                   │   state.py   (SQLite: what is already at each destination)
                   │   locking.py (one run per profile across processes)
                   ▼
                 destinations/  Destination interface → local · sftp · webdav
```

## Packages

| Path | Role |
|---|---|
| `anchor/core/engine.py` | Scan → copy → (mirror-delete) → verify for each destination. Emits `BackupProgress` snapshots. |
| `anchor/core/walker.py` | Walks sources, applies exclusions, reports unreadable folders so mirror-delete is skipped for them. |
| `anchor/core/state.py` | Per-profile SQLite DB of what has been copied to which destination (size, mtime, hash). |
| `anchor/core/profile.py` | `BackupProfile` / `DestinationConfig` dataclasses and atomic JSON persistence. |
| `anchor/destinations/` | `Destination` base class plus adapters. Paths are relative and `/`-separated. Path safety helpers live in `base.py`. |
| `anchor/scheduler.py` | Windows Task Scheduler (`schtasks`) wrapper. |
| `anchor/cli.py` | Headless entry point for scheduled runs. |
| `anchor/gui/controller.py` | `RunController`: the single owner of background threads. Guarantees one job at a time and that a QThread is never destroyed while running. |
| `anchor/gui/pages/` | `DashboardPage` (profile list + detail + live run), `ActivityPage` (log), `SettingsPage`. |
| `anchor/gui/widgets.py` | The Fluent-style widget kit: navigation rail, cards, toggle switch, status pill, stat tile, setting card, toasts. |
| `anchor/gui/theme.py` | Colour tokens for dark and light, the global stylesheet, `ThemeManager.changed` for custom-painted widgets, and the dark title bar. |
| `anchor/gui/icons.py` | Built-in SVG line icons, re-tinted on theme change. |

## Threads and signals

The engine runs on a worker `QThread`. It calls `on_event` with a **copy** of its progress at most ten
times a second, plus forced updates at phase changes. The worker re-emits that as a Qt signal, which
reaches the GUI thread through a queued connection. The controller forwards worker results through
slots on itself (a `QObject` living on the GUI thread), so page code never runs on a worker thread.

`RunController.busy` stays true until `QThread.finished`, not just until the result signal, so a new
job cannot start while the previous thread is still unwinding.

## UI design

The UI follows the Fluent design language: layered surfaces (window → page → card), 1 px borders, 8 px
corners, one accent colour (the TechEase gold). The layout takes ideas from download managers such as
Persepolis and Ghost Downloader: a task list with inline progress, a detail pane and a navigation rail.
All widgets are written on plain PySide6 (no GPL widget library), which keeps Anchor MIT-licensed.
